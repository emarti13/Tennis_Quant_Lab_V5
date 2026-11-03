"""Monthly English-Wikipedia page views per player (a measure of fame), for the popularity test.

Usage:  python research_tests/popularity/fetch_pageviews.py JOINED_PKL OUT_DIR

For each player name in the odds join: find the article ("Name (tennis player)", "Name (tennis)",
then "Name"), accept it only if its summary mentions tennis (so a namesake is not used), follow
redirects to the canonical title, then fetch monthly page views (all access, users only) from
2015-07 to 2025-12. Writes OUT_DIR/articles.csv (name, title, how) and OUT_DIR/views.csv (title,
month, views). Resumable: names and titles already done are skipped. Free public APIs; a fixed
user agent with no personal details.
"""
from __future__ import annotations

import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "TennisQuantLab-research/1.0 (research script; no contact)"}
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
VIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{t}/monthly/2015070100/2025123100"


def get(s, url, tries=4):
    for i in range(tries):
        try:
            r = s.get(url, headers=UA, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** i)
                continue
            return r
        except requests.RequestException:
            time.sleep(2 ** i)
    return None


def find_article(s, name: str):
    base = name.strip().replace(" ", "_")
    for title, how in ((f"{base}_(tennis_player)", "tennis_player"), (f"{base}_(tennis)", "tennis"), (base, "plain")):
        r = get(s, SUMMARY + urllib.parse.quote(title, safe=""))
        if r is None or r.status_code != 200:
            continue
        j = r.json()
        if j.get("type") == "disambiguation":
            continue
        text = (j.get("extract") or "") + " " + (j.get("description") or "")
        if "tennis" in text.lower():
            return j.get("titles", {}).get("canonical") or title, how
    return None, "not_found"


def main() -> int:
    joined_pkl, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    j = pd.read_pickle(joined_pkl)
    j = j[j["tour"].isin(["ATP", "WTA"])]
    names = sorted(set(j["winner_name"].dropna()) | set(j["loser_name"].dropna()))
    art_path, views_path = out / "articles.csv", out / "views.csv"
    arts = pd.read_csv(art_path) if art_path.exists() else pd.DataFrame(columns=["name", "title", "how"])
    done = set(arts["name"])
    s = requests.Session()
    new = []
    for i, n in enumerate(names):
        if n in done:
            continue
        t, how = find_article(s, n)
        new.append({"name": n, "title": t, "how": how})
        if len(new) % 200 == 0:
            arts = pd.concat([arts, pd.DataFrame(new)], ignore_index=True)
            arts.to_csv(art_path, index=False)
            new = []
            print(f"articles {i + 1}/{len(names)}", flush=True)
    arts = pd.concat([arts, pd.DataFrame(new)], ignore_index=True)
    arts.to_csv(art_path, index=False)
    views = pd.read_csv(views_path) if views_path.exists() else pd.DataFrame(columns=["title", "month", "views"])
    have = set(views["title"])
    rows = []
    titles = sorted(set(arts["title"].dropna()) - have)
    for i, t in enumerate(titles):
        r = get(s, VIEWS.format(t=urllib.parse.quote(t, safe="")))
        if r is not None and r.status_code == 200:
            for it in r.json().get("items", []):
                rows.append({"title": t, "month": it["timestamp"][:6], "views": it["views"]})
        else:
            rows.append({"title": t, "month": None, "views": None})
        if (i + 1) % 200 == 0:
            views = pd.concat([views, pd.DataFrame(rows)], ignore_index=True)
            views.to_csv(views_path, index=False)
            rows = []
            print(f"views {i + 1}/{len(titles)}", flush=True)
    views = pd.concat([views, pd.DataFrame(rows)], ignore_index=True)
    views.to_csv(views_path, index=False)
    print(f"done: {len(arts)} names, {arts['title'].notna().sum()} articles, {views['title'].nunique()} with views", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
