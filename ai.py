"""AI 'is it worth claiming?' verdict. Gemini free tier, OpenRouter :free fallback.

Returns None (and the post simply skips the section) if no key is set or both
providers fail, so the AI can never block a giveaway from being posted.
"""
from __future__ import annotations

import json
import os
import time

import requests

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Tried in order: the Flash alias often returns 503 or hangs on the free tier.
GEMINI_MODELS = list(dict.fromkeys([GEMINI_MODEL, "gemini-flash-lite-latest"]))
GEMINI_TIMEOUT = 60
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")
MAX_CHARS = 450


def _key(name: str) -> str:
    """API key from env, without the stray newline/space a pasted secret often has
    (a trailing newline in OPENROUTER_API_KEY made every OpenRouter call fail)."""
    return (os.environ.get(name) or "").strip()

PROMPT = """You judge whether a free game giveaway is worth claiming, for a Telegram channel.
You get the giveaway details and, if found, Steam/Metacritic ratings as JSON.

Write:
- First line: "Worth: N/10" followed by a 2-4 word verdict (e.g. "Claim it", "Worth a look", "Only if curious").
- Then 2-3 short sentences on why: what kind of game it is, who will enjoy it, what the ratings say.

Rules:
- Use only the information in the input. Don't invent features, prices, scores or reviews.
- If there are no ratings, say the verdict is based on the description only.
- Free games cost nothing to claim, so judge whether it's worth the time to play.
- Plain text only. No markdown, no emojis, no links. Under {max_chars} characters.
"""


class AIError(Exception):
    pass


def _post(url: str, headers: dict, body: dict, timeout: int = 120, attempts: int = 2) -> dict:
    for attempt in range(attempts):
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
            time.sleep(min(int(r.headers.get("retry-after", 0) or 0) or 15, 60))
            continue
        raise AIError(f"HTTP {r.status_code}: {r.text[:200]}")
    raise AIError("unreachable")


def _gemini(system: str, user: str) -> str:
    key = _key("GEMINI_API_KEY")
    if not key:
        raise AIError("GEMINI_API_KEY not set")
    last: Exception | None = None
    for model in GEMINI_MODELS:
        try:
            text = _gemini_model(model, key, system, user)
            if text.strip():
                return text
            last = AIError(f"{model} returned empty text")
        except (AIError, requests.RequestException) as e:
            print(f"  Gemini {model} failed: {e}")
            last = e
    raise AIError(f"all Gemini models failed: {last}")


def _gemini_model(model: str, key: str, system: str, user: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    base = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096},
    }
    # Short task: keep reasoning low. Gemini 3 uses thinkingLevel, 2.5 uses thinkingBudget.
    for i, thinking in enumerate([{"thinkingLevel": "low"}, {"thinkingBudget": 512}, None]):
        gc = dict(base["generationConfig"])
        if thinking:
            gc["thinkingConfig"] = thinking
        try:
            # one short attempt: on 503/hang, move on to the next model
            data = _post(url, {"x-goog-api-key": key}, {**base, "generationConfig": gc},
                         timeout=GEMINI_TIMEOUT, attempts=1)
            break
        except AIError as e:
            if "HTTP 400" in str(e) and i < 2:
                continue
            raise
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _openrouter(system: str, user: str) -> str:
    key = _key("OPENROUTER_API_KEY")
    if not key:
        raise AIError("OPENROUTER_API_KEY not set")
    if OPENROUTER_MODEL:
        models = [OPENROUTER_MODEL]
    else:
        r = requests.get("https://openrouter.ai/api/v1/models",
                         headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        free = [m for m in r.json()["data"] if m["id"].endswith(":free")]
        free.sort(key=lambda m: m.get("context_length") or 0, reverse=True)
        models = [m["id"] for m in free[:6]]  # some free models refuse plain API use (403)
    last = None
    for model in models:
        try:
            data = _post("https://openrouter.ai/api/v1/chat/completions",
                         {"Authorization": f"Bearer {key}", "X-Title": "Free Games Radar"},
                         {"model": model, "temperature": 0.4, "messages": [
                             {"role": "system", "content": system},
                             {"role": "user", "content": user}]})
            text = data["choices"][0]["message"]["content"] or ""
            if text.strip():
                return text
        except (AIError, KeyError, IndexError, requests.RequestException) as e:
            last = e
    raise AIError(f"all OpenRouter models failed: {last}")


def _tidy(text: str) -> str:
    text = text.replace("**", "").replace("__", "").strip()
    lines = [l.strip(" -*#") for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        cut = text.rfind(". ", 0, MAX_CHARS)
        text = text[: cut + 1] if cut > 0 else text[:MAX_CHARS].rstrip() + "…"
    return text


def verdict(game: dict, ratings: dict | None) -> str | None:
    if not (_key("GEMINI_API_KEY") or _key("OPENROUTER_API_KEY")):
        return None
    payload = {
        "title": game.get("title"),
        "platforms": game.get("platforms"),
        "normal_price": game.get("worth"),
        "description": game.get("description"),
        "ratings": ratings,
    }
    system = PROMPT.format(max_chars=MAX_CHARS)
    user = json.dumps(payload, ensure_ascii=False)
    for name, fn in (("Gemini", _gemini), ("OpenRouter", _openrouter)):
        try:
            text = _tidy(fn(system, user))
            if text:
                return text
        except (AIError, requests.RequestException) as e:
            print(f"AI verdict via {name} failed: {e}")
    return None
