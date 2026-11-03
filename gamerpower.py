"""GamerPower API."""
from __future__ import annotations

import requests

API = "https://www.gamerpower.com/api"
TIMEOUT = 30


def fetch_active() -> list[dict] | None:
    """Active game giveaways, or None if the API call failed."""
    try:
        r = requests.get(f"{API}/giveaways", params={"type": "game"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else None
    except (requests.RequestException, ValueError) as e:
        print(f"Error fetching giveaways: {e}")
        return None


def is_expired(game_id: str) -> bool | None:
    """True if GamerPower says it ended or no longer exists, None if unknown."""
    try:
        r = requests.get(f"{API}/giveaway", params={"id": game_id}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Could not check giveaway {game_id}: {e}")
        return None
    if data.get("status") == 0:  # {"status":0,"status_message":"No giveaway found..."}
        return True
    return data.get("status") not in ("Active", None)
