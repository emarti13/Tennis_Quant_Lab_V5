
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.oddspapi.io/v4"


class OddsPapiError(RuntimeError):
    pass


def _redact(text, secret):
    s = str(text)
    return s.replace(secret, "[REDACTED_API_KEY]") if secret else s


class OddsPapiClient:
    def __init__(self, api_key=None, timeout=30):
        self.api_key = api_key or os.getenv("ODDSPAPI_KEY")
        if not self.api_key:
            raise OddsPapiError("ODDSPAPI_KEY is not set.")
        self.timeout = timeout

        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:
            pass

        self.session = requests.Session()

    def _get(self, endpoint, **params):
        params = {k: v for k, v in params.items() if v is not None}
        params["apiKey"] = self.api_key
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"

        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.SSLError:
            raise OddsPapiError(
                "SSL certificate verification failed. "
                "Install truststore with: python -m pip install truststore"
            ) from None
        except requests.RequestException as exc:
            raise OddsPapiError(
                _redact(f"OddsPapi request failed: {exc}", self.api_key)
            ) from None

        body = r.text or ""
        content_type = (r.headers.get("content-type") or "").lower()

        # Corporate proxies sometimes return an HTTP 200 HTML block page.
        # Treat HTML as a hard failure rather than pretending it is API data.
        looks_html = (
            "text/html" in content_type
            or body.lstrip().lower().startswith("<!doctype html")
            or "<html" in body[:500].lower()
        )

        if looks_html:
            lower = body.lower()
            if "site blocked" in lower or "content filtering" in lower or "cisco secure access" in lower:
                raise OddsPapiError(
                    "NETWORK_BLOCKED: api.oddspapi.io is being blocked by the current network/content filter. "
                    "Use a personal network/mobile hotspot or run the integration from the deployed cloud app."
                )
            raise OddsPapiError(
                "OddsPapi returned HTML instead of JSON. "
                "The request likely did not reach the API."
            )

        try:
            payload = r.json()
        except Exception:
            raise OddsPapiError(
                f"OddsPapi returned non-JSON content: {_redact(body[:800], self.api_key)}"
            ) from None

        if not r.ok:
            raise OddsPapiError(
                f"OddsPapi HTTP {r.status_code}: {_redact(payload, self.api_key)}"
            )

        return payload

    def account(self):
        return self._get("account")

    def sports(self, language="en"):
        return self._get("sports", language=language)

    def tournaments(self, sport_id, language="en"):
        return self._get("tournaments", sportId=sport_id, language=language)

    def odds_by_tournaments(
        self,
        tournament_ids,
        bookmakers=None,
        language="en",
        verbosity=3,
        odds_format="american",
    ):
        if isinstance(tournament_ids, (list, tuple, set)):
            tournament_ids = ",".join(str(x) for x in tournament_ids)
        if isinstance(bookmakers, (list, tuple, set)):
            bookmakers = ",".join(str(x) for x in bookmakers)

        return self._get(
            "odds-by-tournaments",
            tournamentIds=tournament_ids,
            bookmakers=bookmakers,
            language=language,
            verbosity=verbosity,
            oddsFormat=odds_format,
        )
