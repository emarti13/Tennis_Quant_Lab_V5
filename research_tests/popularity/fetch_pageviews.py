"""Monthly English-Wikipedia page views per player (a measure of fame), for the popularity test.

Usage:  python research_tests/popularity/fetch_pageviews.py JOINED_PKL OUT_DIR

For each player name in the odds join: find the article ("Name (tennis player)", "Name (tennis)",
then "Name"; 50 titles per batch request), accept it only if its short description mentions tennis
and it is not a disambiguation page (so a namesake is not used), follow
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


def get(s, url, tries=8, params=None):
    """GET that waits as long as Wikimedia's Retry-After asks (it throttles clients without contact
    details; no personal details are sent)."""
    for i in range(tries):
        try:
            r = s.get(url, headers=UA, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("retry-after") or 2 ** i) + 1)
                continue
            return r
        except requests.RequestException:
            time.sleep(2 ** i)
    return None


ACTION = "https://en.wikipedia.org/w/api.php"


def find_articles(s, names: list[str]) -> dict:
    """Batch lookup (50 titles per request): for each name try "Name (tennis player)", "Name (tennis)",
    "Name"; accept a page whose short description mentions tennis and is not a disambiguation page."""
    cands = {}
    for n in names:
        base = n.strip()
        for suffix, how in ((" (tennis player)", "tennis_player"), (" (tennis)", "tennis"), ("", "plain")):
            cands.setdefault(n, []).append((base + suffix, how))
    titles = sorted({t for v in cands.values() for t, _ in v})
    info = {}                                   # requested title -> (canonical, is_tennis)
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        r = get(s, ACTION, params={"action": "query", "format": "json", "titles": "|".join(chunk), "redirects": 1,
                                   "prop": "pageprops", "ppprop": "wikibase-shortdesc|disambiguation"})
        if r is None or r.status_code != 200:
            continue
        q = r.json().get("query", {})
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        redir = {x["from"]: x["to"] for x in q.get("redirects", [])}
        pages = {p["title"]: p for p in q.get("pages", {}).values()}
        for t in chunk:
            u = norm.get(t, t)
            u = redir.get(u, u)
            p = pages.get(u)
            if not p or "missing" in p:
                continue
            pp = p.get("pageprops", {})
            info[t] = (u.replace(" ", "_"), "disambiguation" not in pp and "tennis" in pp.get("wikibase-shortdesc", "").lower())
        time.sleep(0.5)
    return {n: next(((info[t][0], how) for t, how in v if t in info and info[t][1]), (None, "not_found")) for n, v in cands.items()}


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
    todo = [n for n in names if n not in done]
    for k in range(0, len(todo), 200):                    # save every 200 names (resumable under rate limits)
        found = find_articles(s, todo[k:k + 200])
        arts = pd.concat([arts, pd.DataFrame([{"name": n, "title": t, "how": h} for n, (t, h) in found.items()])], ignore_index=True)
        arts.to_csv(art_path, index=False)
        print(f"articles: {len(arts)} of {len(names)} names looked up, {arts['title'].notna().sum()} found", flush=True)
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
        if (i + 1) % 50 == 0:
            views = pd.concat([views, pd.DataFrame(rows)], ignore_index=True)
            views.to_csv(views_path, index=False)
            rows = []
            print(f"views {i + 1}/{len(titles)}", flush=True)
        time.sleep(1.0)
    views = pd.concat([views, pd.DataFrame(rows)], ignore_index=True)
    views.to_csv(views_path, index=False)
    print(f"done: {len(arts)} names, {arts['title'].notna().sum()} articles, {views['title'].nunique()} with views", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
