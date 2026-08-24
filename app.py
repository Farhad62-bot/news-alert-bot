"""
Breaking Geopolitical News Alert Monitor (cron-job.org & Render Compatible)
------------------------------------------------------------------------
Watches Google News for geopolitical topics and sends alerts via Telegram.
"""

import feedparser
import requests
import time
import os
import sys
import html
import calendar
import urllib.parse
import logging
from email.utils import parsedate_to_datetime
from threading import Thread
from flask import Flask, Response

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Config ------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8946220251:AAHvtqQRnF2N0deXN91g2RPR--GVR3YB1jQ")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "8776336439")

QUERIES = [
    "Iran attack",
    "Israel Iran strike",
    "Iran nuclear",
    "US military Iran",
    "Israel Gaza strike",
    "China sanctions",
    "Trump Iran",
    "Trump sanctions",
    "Middle East war",
    "oil sanctions",
    "Russia Ukraine strike",
    "Strait of Hormuz",
    "Strait of Hormuz oil",
    "Iran Strait of Hormuz closure",
    "oil price surge Iran",
    "gold price safe haven",
    "gold surge war",
    "OPEC oil supply",
    "dollar safe haven flows",
]

MAX_AGE_MINUTES = 20  # Freshness window
BOT_LABEL = "BERLIN NEWS BOT"

# Global memory storage for deduplication
SEEN_ARTICLES = set()

CRITICAL_KEYWORDS = [
    "attack", "strike", "invasion", "invades", "nuclear", "missile",
    "explosion", "airstrike", "bombing", "war declared", "declares war",
    "closes strait", "closure of hormuz", "blocks strait", "blockade",
    "market crash", "flash crash", "emergency", "assassinat", "coup",
    "state of emergency", "military action", "troops deployed",
    "evacuat", "ceasefire collapse", "retaliat",
]

# --- Flask Server -----------------------------------------------------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Berlin News Bot is active and running!", 200

@flask_app.route('/trigger-news')
def trigger_news():
    """Triggered by cron-job.org periodically."""
    Thread(target=run_once).start()
    # Return minimal response to prevent "output too large" on cron-job.org
    return Response("OK", status=200, mimetype='text/plain')

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask health check server on port {port}...")
    flask_app.run(host='0.0.0.0', port=port)


# --- Telegram Functions -----------------------------------------------

def is_critical(title):
    t = title.lower()
    return any(k in t for k in CRITICAL_KEYWORDS)


def pin_message(message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/pinChatMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "disable_notification": False},
            timeout=10
        )
        if r.status_code != 200:
            logger.error(f"Pin failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"Pin request crashed: {e}")


def send_telegram(text, pin=False):
    if not TELEGRAM_BOT_TOKEN or "YOUR_BOT_TOKEN" in TELEGRAM_BOT_TOKEN:
        logger.warning("[Telegram not configured] Would have sent:\n" + text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=10
        )
        if r.status_code != 200:
            logger.error(f"Telegram error: {r.status_code} {r.text}")
            return False
        if pin:
            message_id = r.json().get("result", {}).get("message_id")
            if message_id:
                pin_message(message_id)
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def build_message(query, title, link):
    safe_title = html.escape(title, quote=False)
    safe_query = html.escape(query, quote=False)
    safe_link = html.escape(link, quote=True)

    if is_critical(title):
        header = f"<b>{BOT_LABEL}</b>\n🔴🚨 <b>THIS IS VERY BAD — HIGH IMPACT</b> 🚨🔴"
    else:
        header = f"<b>{BOT_LABEL}</b>\n📰 Breaking"

    return (
        f"{header} ({safe_query})\n\n"
        f"{safe_title}\n\n"
        f'🔗 <a href="{safe_link}">Read full story</a>'
    )


# --- Feed Fetching ---------------------------------------------------

def build_google_news_url(query):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def get_entry_age_minutes(entry, now_ts):
    """Calculates entry age in minutes using multiple timestamp parsing fallbacks."""
    published_ts = None
    
    if entry.get("published_parsed"):
        published_ts = calendar.timegm(entry.published_parsed)
    elif entry.get("published"):
        try:
            dt = parsedate_to_datetime(entry.published)
            published_ts = dt.timestamp()
        except Exception:
            pass

    if published_ts is None:
        return None

    return (now_ts - published_ts) / 60.0


def fetch_recent_items(max_age_minutes):
    global SEEN_ARTICLES
    now_ts = time.time()
    items = []
    
    for query in QUERIES:
        url = build_google_news_url(query)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.error(f"Failed to fetch feed for '{query}': {e}")
            continue
            
        for entry in feed.entries[:10]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title:
                continue

            age = get_entry_age_minutes(entry, now_ts)
            if age is None or age > max_age_minutes or age < 0:
                continue

            # Normalized headline deduplication
            normalized_title = title.lower().replace(" ", "")
            if normalized_title in SEEN_ARTICLES:
                continue
                
            SEEN_ARTICLES.add(normalized_title)
            items.append((query, title, link))

    # Prevent memory growth over time
    if len(SEEN_ARTICLES) > 2000:
        SEEN_ARTICLES = set(list(SEEN_ARTICLES)[-1000:])

    return items


# --- Execution Modes -------------------------------------------------

def run_test():
    logger.info("Sending a test message to Telegram...")
    ok = send_telegram(f"<b>{BOT_LABEL}</b>\n✅ Test message. If you see this, setup is working.")
    logger.info("Sent OK." if ok else "FAILED to send — check your bot token / chat ID.")
    sys.exit(0 if ok else 1)


def run_once():
    items = fetch_recent_items(MAX_AGE_MINUTES)
    logger.info(f"[cron trigger] Checked {len(QUERIES)} topics, found {len(items)} fresh item(s).")
    for query, title, link in items:
        msg = build_message(query, title, link)
        critical = is_critical(title)
        send_telegram(msg, pin=critical)


# --- Main Entry Point ------------------------------------------------

if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    elif "--once" in sys.argv:
        run_once()
    else:
        server_thread = Thread(target=run_web_server, daemon=True)
        server_thread.start()
        server_thread.join()
