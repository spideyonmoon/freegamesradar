"""Free Games Radar: post new GamerPower game giveaways to Telegram channels.

Each run (hourly on GitHub Actions):
  1. posts new giveaways (with Steam ratings + AI verdict dropdowns) to every channel,
     retrying channels that failed last time without double-posting the others;
  2. edits earlier posts whose giveaway has ended so they show "ended".
"""
from __future__ import annotations

import json
import os
import sys
import time

import ai
import gamerpower
import ratings
import state
import tg

CONFIG_FILE = "config.json"
MAX_ATTEMPTS = 5      # runs to keep retrying a channel that rejects a post
SEND_DELAY = 3        # seconds between posts (Telegram allows ~20/min per channel)


def load_config() -> dict:
    """Priority: env vars > config.json."""
    config: dict = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not read {CONFIG_FILE}: {e}")
    if os.environ.get("BOT_TOKEN"):
        config["bot_token"] = os.environ["BOT_TOKEN"]
    if os.environ.get("CHANNEL_IDS"):
        config["channel_ids"] = [x.strip() for x in os.environ["CHANNEL_IDS"].split(",") if x.strip()]
    return config


def post_new(games: list[dict], data: dict, channels: list[str]) -> bool:
    changed = False
    # oldest first, so the newest ends up at the bottom of the channel
    for game in reversed(games):
        gid = str(game.get("id") or "")
        if not gid or game.get("type") != "Game":
            continue
        entry = data["games"].get(gid)
        if entry is None:
            print(f"New: {game.get('title')}")
            r = ratings.lookup(game.get("title", ""))
            v = ai.verdict(game, r)
            print(f"  ratings: {'yes' if r else 'none'}, AI verdict: {'yes' if v else 'none'}")
            entry = {"posts": [], "pending": list(channels), "attempts": 0,
                     "expired": False, "post": tg.build_post(game, r, v)}
            data["games"][gid] = entry
        if not entry.get("pending"):
            continue

        for chat in list(entry["pending"]):
            sent = tg.send(chat, entry["post"])
            if sent:
                mode, message_id = sent
                entry["posts"].append({"chat": chat, "message_id": message_id, "mode": mode})
                entry["pending"].remove(chat)
                print(f"  sent to {chat} ({mode})")
            time.sleep(SEND_DELAY)

        entry["attempts"] = entry.get("attempts", 0) + 1
        if entry["pending"] and entry["attempts"] >= MAX_ATTEMPTS:
            print(f"  giving up on {entry['pending']} after {MAX_ATTEMPTS} runs")
            entry["pending"] = []
        changed = True
        state.save(data)  # save as we go, so a crash can't cause re-posts
    return changed


def mark_ended(active: list[dict], data: dict) -> bool:
    active_ids = {str(g.get("id")) for g in active}
    changed = False
    for gid, entry in data["games"].items():
        if entry.get("expired") or not entry.get("posts") or not entry.get("post"):
            continue
        if gid in active_ids:
            continue
        if gamerpower.is_expired(gid) is not True:
            continue
        print(f"Ended: {entry['post']['title']}")
        remaining = []
        for post in entry["posts"]:
            if not tg.mark_expired(post["chat"], post["message_id"], post["mode"], entry["post"]):
                remaining.append(post)
            time.sleep(1)
        entry["posts"] = remaining
        if not remaining:
            entry["expired"] = True
            entry.pop("post", None)  # no longer needed, keeps the file small
        changed = True
    return changed


def main() -> None:
    config = load_config()
    token, channels = config.get("bot_token"), config.get("channel_ids")
    if not token or not channels:
        print("Error: bot_token or channel_ids missing in config or env vars.")
        sys.exit(1)
    os.environ["BOT_TOKEN"] = token

    data = state.load()
    games = gamerpower.fetch_active()
    if games is None:
        print("GamerPower unavailable, nothing to do this run.")
        return

    changed = post_new(games, data, channels)
    # Only judge expiry from a non-empty list, so an API hiccup can't mark everything ended
    if games:
        changed = mark_ended(games, data) or changed

    if changed:
        state.save(data)
        print("Updated sent games list.")
    else:
        print("No new games found.")


if __name__ == "__main__":
    main()
