import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from streamlit.testing.v1 import AppTest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "tennis_quant_app_v5.py"


@pytest.fixture(scope="module")
def rendered_app():
    return AppTest.from_file(str(APP_PATH), default_timeout=120).run()


def test_streamlit_server_exposes_healthy_endpoint():
    port = 8501
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_PATH),
            "--server.headless=true",
            f"--server.port={port}",
            "--browser.gatherUsageStats=false",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        deadline = time.monotonic() + 60
        last_error = None

        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                pytest.fail(
                    "Streamlit exited before becoming healthy.\n"
                    f"Exit code: {process.returncode}\n{output}"
                )

            try:
                with urlopen(
                    f"http://127.0.0.1:{port}/_stcore/health",
                    timeout=2,
                ) as response:
                    body = response.read().decode("utf-8").strip()
                    assert response.status == 200
                    assert body == "ok"
                    return
            except (OSError, URLError) as exc:
                last_error = exc
                time.sleep(0.5)

        pytest.fail(f"Streamlit did not become healthy within 60 seconds: {last_error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_app_renders_without_uncaught_exception(rendered_app):
    assert not rendered_app.exception, [
        exception.value for exception in rendered_app.exception
    ]


def test_primary_navigation_exposes_daily_board_and_decision_feed(rendered_app):
    assert len(rendered_app.sidebar.radio) == 1
    assert list(rendered_app.sidebar.radio[0].options) == [
        "Daily Board",
        "Decision Feed",
        "Match Detail",
        "All Markets",
        "Performance",
        "Model Health",
        "Matchup Lab",
    ]
    assert rendered_app.sidebar.radio[0].value == "Daily Board"
