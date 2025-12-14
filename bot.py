import requests
import time
import json
import os
import sys

# Constants
API_URL = "https://www.gamerpower.com/api/giveaways"
CONFIG_FILE = "config.json"

def load_config():
    # Priority: Env Vars > Config File
    config = {}
    
    # Try loading from file first
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                config = json.load(f)
            except:
                pass
    
    # Override with Env Vars (for GitHub Actions)
    if os.environ.get("BOT_TOKEN"):
        config["bot_token"] = os.environ.get("BOT_TOKEN")
    
    # Channel IDs environment variable should be a comma-separated string
    # e.g., CHANNEL_IDS="@channel1,@channel2"
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
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # Construct message
    title = game.get('title', 'Unknown Game')
    platform = game.get('platforms', 'Unknown Platform')
    worth = game.get('worth', 'N/A')
    description = game.get('description', 'No description.')
    open_giveaway_url = game.get('open_giveaway')
    image_url = game.get('image')

    text = (
        f"<b>{title}</b>\n\n"
        f"🎮 <b>Platform:</b> {platform}\n"
        f"💰 <b>Worth:</b> {worth}\n"
        f"🏪 <b>Source:</b> {game.get('end_date', 'GamerPower')}\n\n"
        f"{description}\n"
    )

    if image_url:
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        data = {
            "chat_id": channel_id,
            "photo": image_url,
            "caption": text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps({
                "inline_keyboard": [[
                    {"text": "🔥 Claim Now", "url": open_giveaway_url}
                ]]
            })
        }
    else:
        data = {
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps({
                "inline_keyboard": [[
                    {"text": "🔥 Claim Now", "url": open_giveaway_url}
                ]]
            })
        }
    
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        print(f"Sent {title} to {channel_id}")
        return True
    except requests.RequestException as e:
        print(f"Failed to send message to {channel_id}: {e}")
        if response.content:
            print(f"Response: {response.content}")
        return False

def main():
    config = load_config()
    bot_token = config.get("bot_token")
    channel_ids = config.get("channel_ids")
    check_interval = config.get("check_interval", 600)
    sent_games_file = config.get("sent_games_file", "sent_games.json")
    
    # Check if running in single-run mode (good for Cron jobs)
    # We can use an env var SINGLE_RUN or a command line arg.
    single_run = os.environ.get("SINGLE_RUN", "false").lower() == "true"

    if not bot_token or not channel_ids:
        print("Error: bot_token or channel_ids missing in config or env vars.")
        sys.exit(1)

    print(f"Bot started. Single run mode: {single_run}")

    while True:
        sent_games = load_sent_games(sent_games_file)
        sent_ids = set(sent_games) 

        games = fetch_giveaways()
        
        new_games_found = False

        for game in games:
            game_id = game.get('id')
            
            if game_id and game_id not in sent_ids:
                if game.get('type') != 'Game': 
                    continue
                
                all_sent = True
                for channel_id in channel_ids:
                    if not send_telegram_message(bot_token, channel_id, game):
                        all_sent = False
                    time.sleep(1) # Be polite to Telegram API
                
                if all_sent:
                    sent_ids.add(game_id)
                    new_games_found = True

        if new_games_found:
            save_sent_games(sent_games_file, list(sent_ids))
            print(f"Updated sent games list.")
        
        if single_run:
            print("Single run complete. Exiting.")
            break
        
        print(f"Sleeping for {check_interval} seconds...")
        time.sleep(check_interval)

if __name__ == "__main__":
    main()
