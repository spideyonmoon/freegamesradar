import requests
import json
import os
import sys

# Constants
API_URL = "https://www.gamerpower.com/api/giveaways"
CONFIG_FILE = "config.json"
SENT_GAMES_FILE = "sent_games.json"

def load_config():
    # Priority: Env Vars > Config File
    config = {}
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                config = json.load(f)
            except:
                pass
    
    # Override with Env Vars
    if os.environ.get("BOT_TOKEN"):
        config["bot_token"] = os.environ.get("BOT_TOKEN")
    
    if os.environ.get("CHANNEL_IDS"):
        ids = os.environ.get("CHANNEL_IDS").split(",")
        config["channel_ids"] = [x.strip() for x in ids if x.strip()]
        
    return config

def load_sent_games(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_sent_games(filepath, sent_games):
    with open(filepath, 'w') as f:
        json.dump(sent_games, f)

def fetch_giveaways():
    try:
        # Filter by type=game directly in the API call
        response = requests.get(API_URL, params={"type": "game"})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching giveaways: {e}")
        return []

def send_telegram_message(bot_token, channel_id, game):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    # Construct message data
    title = game.get('title', 'Unknown Game')
    platform = game.get('platforms', 'Unknown Platform')
    worth = game.get('worth', 'N/A')
    description = game.get('description', 'No description.')
    open_giveaway_url = game.get('open_giveaway')
    image_url = game.get('image')
    end_date = game.get('end_date')

    # 
    text = (
        f"<b>{title}</b>\n\n"
        f"🎮 <b>Platform:</b> {platform}\n"
        f"💰 <b>Worth:</b> {worth}\n"
    )

    # Fixed: Label is now 'Ends' instead of 'Source', and checks if date exists
    if end_date and end_date != "N/A":
        text += f"⏳ <b>Ends:</b> {end_date}\n"

    # Truncate description slightly to keep it clean
    if len(description) > 300:
        description = description[:297] + "..."
    
    text += f"\n{description}"

    # Clean Button (No Fire Emoji)
    reply_markup = {
        "inline_keyboard": [[
            {"text": "Claim Now ↗️", "url": open_giveaway_url}
        ]]
    }

    # Prepare Payload
    data = {
        "chat_id": channel_id,
        "caption": text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(reply_markup)
    }

    if image_url:
        data["photo"] = image_url
    else:
        # Fallback to text message if no image
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data["text"] = text
        del data["caption"]
        del data["photo"]
    
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Failed to send message to {channel_id}: {e}")
        return False

def main():
    config = load_config()
    bot_token = config.get("bot_token")
    channel_ids = config.get("channel_ids")
    
    if not bot_token or not channel_ids:
        print("Error: bot_token or channel_ids missing in config or env vars.")
        sys.exit(1)

    print("Bot started (Single Run Mode).")

    sent_games = load_sent_games(SENT_GAMES_FILE)
    sent_ids = set(sent_games) 

    games = fetch_giveaways()
    
    new_games_found = False

    # Reversed: Process oldest games first so they appear at the top of the chat
    for game in reversed(games):
        game_id = game.get('id')
        
        if game_id and game_id not in sent_ids:
            # Original simple check as requested
            if game.get('type') != 'Game': 
                continue
            
            all_sent = True
            for channel_id in channel_ids:
                if not send_telegram_message(bot_token, channel_id, game):
                    all_sent = False
            
            if all_sent:
                print(f"Sent: {game.get('title')}")
                sent_ids.add(game_id)
                new_games_found = True

    if new_games_found:
        save_sent_games(SENT_GAMES_FILE, list(sent_ids))
        print("Updated sent games list.")
    else:
        print("No new games found.")

if __name__ == "__main__":
    main()
