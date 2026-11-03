"""sent_games.json: what was posted where, so we can retry and mark expiry.

Format (version 2):
{
  "version": 2,
  "games": {
    "3842": {
      "posts":   [{"chat": "@ch", "message_id": 12, "mode": "rich"}],
      "pending": ["@other"],      # channels still to post to
      "attempts": 1,              # runs that tried the pending channels
      "expired": false,
      "post": {...}               # what was posted, kept so it can be re-rendered as expired
    }
  }
}
The old format (a plain list of ids) is migrated to entries with no posts:
those are treated as done and never edited.
"""
from __future__ import annotations

import json
import os

SENT_GAMES_FILE = "sent_games.json"


def load(path: str = SENT_GAMES_FILE) -> dict:
    if not os.path.exists(path):
        return {"version": 2, "games": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"Warning: {path} unreadable, starting fresh")
        return {"version": 2, "games": {}}

    if isinstance(data, list):  # v1: list of ids already posted
        return {"version": 2, "games": {
            str(i): {"posts": [], "pending": [], "attempts": 0, "expired": False} for i in data}}
    data.setdefault("games", {})
    return data


def save(data: dict, path: str = SENT_GAMES_FILE) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
