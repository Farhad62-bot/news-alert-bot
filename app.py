import os
import time
import logging
from threading import Thread
from flask import Flask
import requests

# Enable logging to monitor execution in Render logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. FLASK WEB SERVER (Keeps Render Health Check Happy)
# ---------------------------------------------------------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is active and running!", 200

def run_web_server():
    # Render automatically sets the PORT environment variable (defaults to 10000)
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}...")
    flask_app.run(host='0.0.0.0', port=port)


# ---------------------------------------------------------
# 2. TELEGRAM BOT & NEWS LOGIC
# ---------------------------------------------------------
# Credentials hardcoded or pulled from environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8946220251:AAHvtqQRnF2N0deXN91g2RPR--GVR3YB1jQ")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8776336439")

def send_telegram_message(message_text):
    """Sends a text message to your specified Telegram chat/channel."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Successfully sent message to Telegram.")
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending message to Telegram: {e}")

def fetch_and_send_news():
    """Place your news scraping or API logic here."""
    # EXAMPLE NEWS LOGIC: Replace this placeholder with your actual news-fetching code
    news_items = [
        "<b>Latest News Update</b>\n\nYour news alert bot is active and running successfully!"
    ]
    
    for item in news_items:
        send_telegram_message(item)

def news_loop():
    """Background loop that periodically checks and posts news."""
    logger.info("Starting news fetch loop...")
    
    # Startup test notification sent directly to your Telegram chat
    send_telegram_message("🤖 Bot has successfully connected and deployed on Render!")
    
    while True:
        try:
            fetch_and_send_news()
        except Exception as e:
            logger.error(f"Error in news loop execution: {e}")
            
        # Check for news every 15 minutes (900 seconds)
        time.sleep(900)


# ---------------------------------------------------------
# 3. MAIN APPLICATION ENTRYPOINT
# ---------------------------------------------------------
if __name__ == '__main__':
    # Start Flask web server in a separate thread so Render gets its port 10000 response
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()

    # Run the news fetching loop on the main thread
    news_loop()
