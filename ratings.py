"""Steam ratings for a giveaway, matched by name.

Steam store search -> app id -> review counts (Steam's appreviews, falling
back to SteamSpy) + Metacritic score, genres and release date from appdetails.
Returns None when no confident match is found.
"""
from __future__ import annotations

import difflib
import re

import requests

TIMEOUT = 20
UA = {"User-Agent": "freegamesradar/2.0 (+https://github.com/spideyonmoon/freegamesradar)"}


def clean_title(title: str) -> str:
    """'Highway Driving (Epic Games) Giveaway' -> 'Highway Driving'."""
    name = re.sub(r"\s*\([^)]*\)", "", title)
    name = re.sub(r"\b(giveaway|free|key)\b", "", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" -:")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _get(url: str, **params) -> dict | None:
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def find_app(name: str) -> dict | None:
    data = _get("https://store.steampowered.com/api/storesearch/", term=name, cc="us", l="en")
    if not data:
        return None
    target = _norm(name)
    best, best_score = None, 0.0
    for item in data.get("items", []):
        score = difflib.SequenceMatcher(None, target, _norm(item["name"])).ratio()
        if score > best_score:
            best, best_score = item, score
    return best if best and best_score >= 0.9 else None


def review_label(pct: float, total: int) -> str | None:
    """Steam's own wording for a positive % and review count."""
    if total < 10:
        return None
    if pct >= 80:
        if pct >= 95 and total >= 500:
            return "Overwhelmingly Positive"
        return "Very Positive" if total >= 50 else "Positive"
    if pct >= 70:
        return "Mostly Positive"
    if pct >= 40:
        return "Mixed"
    if pct >= 20:
        return "Mostly Negative"
    if total >= 500:
        return "Overwhelmingly Negative"
    return "Very Negative" if total >= 50 else "Negative"


def _reviews(appid: int) -> tuple[int, int] | None:
    data = _get(f"https://store.steampowered.com/appreviews/{appid}",
                json=1, language="all", purchase_type="all", num_per_page=0)
    if data and data.get("success") == 1:
        q = data["query_summary"]
        return q.get("total_positive", 0), q.get("total_negative", 0)
    data = _get("https://steamspy.com/api.php", request="appdetails", appid=appid)
    if data and "positive" in data:
        return int(data["positive"]), int(data["negative"])
    return None


def lookup(title: str) -> dict | None:
    name = clean_title(title)
    if not name:
        return None
    app = find_app(name)
    if not app:
        return None
    appid = app["id"]
    out: dict = {"name": app["name"], "url": f"https://store.steampowered.com/app/{appid}/"}

    rv = _reviews(appid)
    if rv:
        pos, neg = rv
        total = pos + neg
        if total:
            pct = round(pos / total * 100)
            out.update(steam_pct=pct, steam_reviews=total, steam_label=review_label(pct, total))

    details = _get("https://store.steampowered.com/api/appdetails",
                   appids=appid, filters="metacritic,genres,release_date")
    d = (details or {}).get(str(appid), {})
    if d.get("success"):
        d = d.get("data") or {}
        if d.get("metacritic", {}).get("score"):
            out["metacritic"] = d["metacritic"]["score"]
        if d.get("genres"):
            out["genres"] = [g["description"] for g in d["genres"]][:4]
        if d.get("release_date", {}).get("date"):
            out["released"] = d["release_date"]["date"]

    has_scores = "steam_pct" in out or "metacritic" in out
    return out if has_scores else None
