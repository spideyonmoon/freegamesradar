"""Rendering, sending and editing giveaway posts.

Posts go out as Telegram rich messages (Bot API 10.1+), where Ratings and
AI verdict are real dropdowns (<details>). If that fails, it falls back to the
classic photo-with-caption post, where the dropdowns become expandable quotes,
and finally to a plain text message if the image can't be used.
The mode used is stored so the post can be edited the same way when it expires.
"""
from __future__ import annotations

import html
import os
import random
import re
import time

import requests

TIMEOUT = 30
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
POST_MODE = os.getenv("POST_MODE", "rich")  # "rich" or "classic"


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def attr(s) -> str:
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------
# Post content
# ---------------------------------------------------------------------------

def build_post(game: dict, ratings: dict | None, verdict: str | None) -> dict:
    desc = game.get("description") or "No description."
    if len(desc) > 300:
        desc = desc[:297].rstrip() + "..."
    end = game.get("end_date")
    return {
        "title": game.get("title") or "Unknown Game",
        "platforms": game.get("platforms") or "Unknown Platform",
        "worth": game.get("worth") or "N/A",
        "ends": end if end and end != "N/A" else None,
        "description": desc,
        "url": game.get("open_giveaway") or game.get("open_giveaway_url") or game.get("gamerpower_url"),
        "image": game.get("image") or game.get("thumbnail"),
        "ratings": ratings,
        "verdict": verdict,
    }


def _rating_lines(r: dict) -> list[str]:
    """Escaped HTML lines for the Ratings section."""
    lines = []
    if "steam_pct" in r:
        label = f", {esc(r['steam_label'])}" if r.get("steam_label") else ""
        lines.append(f"Steam: <b>{r['steam_pct']}%</b> positive of {r['steam_reviews']:,} reviews{label}")
    if "metacritic" in r:
        lines.append(f"Metacritic: <b>{r['metacritic']}</b>")
    if r.get("genres"):
        lines.append(f"Genre: {esc(', '.join(r['genres']))}")
    if r.get("released"):
        lines.append(f"Released: {esc(r['released'])}")
    lines.append(f'<a href="{attr(r["url"])}">Steam page</a>')
    return lines


ENDED_LINES = {
    "high": [
        "Was a {n}/10. Shame if you missed it.",
        "That was a {n}/10. Hope you grabbed it.",
        "{n}/10, and it's gone now. Keep an eye out next time.",
        "Was a solid {n}/10. If you got it, nice one.",
        "A {n}/10 that's now over. Ouch if you slept on it.",
    ],
    "mid": [
        "Was a {n}/10. Decent, but nothing to lose sleep over.",
        "That one was a {n}/10. No big loss if you missed it.",
        "{n}/10, now over. Fine if you skipped it.",
        "Was an okay {n}/10. Plenty more where that came from.",
    ],
    "low": [
        "Was {n}/10. It's alright if you didn't bother.",
        "Only a {n}/10. You didn't miss much.",
        "{n}/10, and it's gone. Probably for the best.",
        "Was a {n}/10. Skipping it was a fine call.",
    ],
    "none": [
        "This one's over now.",
        "Giveaway's done. Catch the next one.",
    ],
}


def ended_line(verdict: str | None) -> str | None:
    """Past-tense replacement for "Worth: N/10 Claim it", picked at random by score."""
    if not verdict:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", verdict.partition("\n")[0])
    if not m:
        return random.choice(ENDED_LINES["none"])
    n = float(m.group(1))
    tier = "high" if n >= 8 else "mid" if n >= 5 else "low"
    return random.choice(ENDED_LINES[tier]).format(n=m.group(1))


def _verdict_html(v: str, sep: str, head_override: str | None = None) -> str:
    """First line ("Worth: 8/10 Claim it") in bold, the reasoning below."""
    head, _, rest = v.partition("\n")
    head = head_override or head
    return f"<b>{esc(head)}</b>" + (sep + esc(rest).replace("\n", sep) if rest else "")


def _info_lines(p: dict) -> list[str]:
    lines = [f"🎮 <b>Platform:</b> {esc(p['platforms'])}", f"💰 <b>Worth:</b> {esc(p['worth'])}"]
    if p["ends"]:
        lines.append(f"⏳ <b>Ends:</b> {esc(p['ends'])}")
    return lines


def keyboard(p: dict) -> dict | None:
    if not p.get("url"):
        return None
    return {"inline_keyboard": [[{"text": "Claim Now ↗️", "url": p["url"]}]]}


def render_rich(p: dict, expired: bool = False, with_image: bool = True) -> str:
    parts = []
    if with_image and p.get("image"):
        parts.append(f'<img src="{attr(p["image"])}"/>')
    if expired:
        parts.append("<p>❌ <b>This giveaway has ended.</b></p>")
        parts.append(f"<h3><s>{esc(p['title'])}</s></h3>")
    else:
        parts.append(f"<h3>{esc(p['title'])}</h3>")
    parts.append("<p>" + "<br>".join(_info_lines(p)) + "</p>")
    parts.append(f"<p>{esc(p['description'])}</p>")
    if p.get("ratings"):
        parts.append("<details><summary>⭐ Ratings</summary><p>"
                     + "<br>".join(_rating_lines(p["ratings"])) + "</p></details>")
    if p.get("verdict"):
        parts.append("<details><summary>🤖 AI verdict</summary><p>"
                     + _verdict_html(p["verdict"], "<br>", p.get("ended_line") if expired else None)
                     + "</p></details>")
    return "\n".join(parts)


def render_classic(p: dict, expired: bool = False, limit: int = CAPTION_LIMIT) -> str:
    """Caption/text HTML. Dropdowns become expandable block quotes."""
    def build(desc: str, verdict: str | None) -> str:
        head = (f"❌ <b>This giveaway has ended.</b>\n\n<b><s>{esc(p['title'])}</s></b>"
                if expired else f"<b>{esc(p['title'])}</b>")
        text = head + "\n\n" + "\n".join(_info_lines(p)) + "\n\n" + esc(desc)
        if p.get("ratings"):
            text += "\n\n<blockquote expandable>⭐ <b>Ratings</b>\n" + "\n".join(_rating_lines(p["ratings"])) + "</blockquote>"
        if verdict:
            text += ("\n<blockquote expandable>🤖 <b>AI verdict</b>\n"
                     + _verdict_html(verdict, "\n", p.get("ended_line") if expired else None) + "</blockquote>")
        return text

    desc, verdict = p["description"], p.get("verdict")
    text = build(desc, verdict)
    # Telegram counts the limit after tags are removed; tags are a safe overestimate.
    while len(_visible(text)) > limit and verdict and len(verdict) > 80:
        verdict = verdict[: max(80, len(verdict) - 60)].rsplit(" ", 1)[0] + "…"
        text = build(desc, verdict)
    while len(_visible(text)) > limit and len(desc) > 60:
        desc = desc[: max(60, len(desc) - 60)].rsplit(" ", 1)[0] + "..."
        text = build(desc, verdict)
    return text


def _visible(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


# ---------------------------------------------------------------------------
# Bot API
# ---------------------------------------------------------------------------

def call(method: str, payload: dict) -> tuple[bool, dict]:
    """POST to the Bot API with rate-limit retries. Returns (ok, response json)."""
    url = f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/{method}"
    body: dict = {}
    for _ in range(4):
        try:
            r = requests.post(url, json=payload, timeout=TIMEOUT)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            body = {"ok": False, "description": str(e)}
            time.sleep(3)
            continue
        if r.status_code == 429:
            wait = body.get("parameters", {}).get("retry_after", 5)
            print(f"Telegram rate limit, waiting {wait}s")
            time.sleep(wait + 1)
            continue
        return bool(body.get("ok")), body
    return False, body


def send(chat: str, p: dict) -> tuple[str, int] | None:
    """Post to one channel. Returns (mode, message_id) or None."""
    kb = keyboard(p)
    attempts = []
    if POST_MODE == "rich":
        if p.get("image"):
            attempts.append(("rich", "sendRichMessage",
                             {"rich_message": {"html": render_rich(p)}}))
        attempts.append(("rich_noimg", "sendRichMessage",
                         {"rich_message": {"html": render_rich(p, with_image=False)}}))
    if p.get("image"):
        attempts.append(("photo", "sendPhoto",
                         {"photo": p["image"], "caption": render_classic(p), "parse_mode": "HTML"}))
    attempts.append(("text", "sendMessage", {
        "text": render_classic(p, limit=TEXT_LIMIT), "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True}}))

    for mode, method, extra in attempts:
        payload = {"chat_id": chat, **extra}
        if kb:
            payload["reply_markup"] = kb
        ok, body = call(method, payload)
        if ok:
            return mode, body["result"]["message_id"]
        print(f"  {method} ({mode}) to {chat} failed: {body.get('description')}")
    return None


def mark_expired(chat: str, message_id: int, mode: str, p: dict) -> bool:
    """Edit a post to show the giveaway ended. Omitting reply_markup drops the Claim button."""
    base = {"chat_id": chat, "message_id": message_id}
    if mode in ("rich", "rich_noimg"):
        method, extra = "editMessageText", {
            "rich_message": {"html": render_rich(p, expired=True, with_image=mode == "rich")}}
    elif mode == "photo":
        method, extra = "editMessageCaption", {
            "caption": render_classic(p, expired=True), "parse_mode": "HTML"}
    else:
        method, extra = "editMessageText", {
            "text": render_classic(p, expired=True, limit=TEXT_LIMIT), "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True}}
    ok, body = call(method, {**base, **extra})
    desc = (body.get("description") or "").lower()
    # already edited, or deleted by an admin: nothing left to do
    if ok or "not modified" in desc or "not found" in desc:
        return True
    print(f"  {method} on {chat}/{message_id} failed: {body.get('description')}")
    return False
