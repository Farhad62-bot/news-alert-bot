"""
Breaking Geopolitical News Alert Monitor (Render Web Service Compatible)
------------------------------------------------------------------------
Watches Google News for geopolitical topics and sends alerts via Telegram.
Runs a background Flask web server to satisfy Render's port 10000 health check.
"""

import feedparser
import requests
import time
import json
import os
import sys
import html
import calendar
import urllib.parse
import logging
from threading import Thread
from flask import Flask

# Enable logging for Render console tracking
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

CHECK_INTERVAL_SECONDS = 900     # 15 minutes polling loop
MAX_AGE_MINUTES = 16             # once mode
SEEN_FILE = "seen_news.json"
MAX_SEEN_STORED = 3000

BOT_LABEL = "BERLIN NEWS BOT"

CRITICAL_KEYWORDS = [
    "attack", "strike", "invasion", "invades", "nuclear", "missile",
    "explosion", "airstrike", "bombing", "war declared", "declares war",
    "closes strait", "closure of hormuz", "blocks strait", "blockade",
    "market crash", "flash crash", "emergency", "assassinat", "coup",
    "state of emergency", "military action", "troops deployed",
    "evacuat", "ceasefire collapse", "retaliat",
]

# --- Flask Server (Keeps Render Health Check Alive) -------------------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Berlin News Bot is active and running!", 200

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


def entry_age_minutes(entry, now_ts):
    if not entry.get("published_parsed"):
        return None
    published_ts = calendar.timegm(entry.published_parsed)
    return (now_ts - published_ts) / 60.0


def fetch_recent_items(max_age_minutes):
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
            age = entry_age_minutes(entry, now_ts)
            if age is None or age > max_age_minutes or age < 0:
                continue
            items.append((query, entry.get("title", "No title"), entry.get("link", "")))
    return items


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-MAX_SEEN_STORED:], f)


def fetch_all_items():
    items = []
    for query in QUERIES:
        url = build_google_news_url(query)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.error(f"Failed to fetch feed for '{query}': {e}")
            continue
        for entry in feed.entries[:10]:
            items.append((query, entry.get("title", "No title"), entry.get("link", ""),
                          entry.get("id") or entry.get("link")))
    return items


# --- Execution Modes -------------------------------------------------

def run_test():
    logger.info("Sending a test message to Telegram...")
    ok = send_telegram(f"<b>{BOT_LABEL}</b>\n✅ Test message. If you see this, setup is working.")
    logger.info("Sent OK." if ok else "FAILED to send — check your bot token / chat ID.")
    sys.exit(0 if ok else 1)


def run_once():
    items = fetch_recent_items(MAX_AGE_MINUTES)
    logger.info(f"[once] Checked {len(QUERIES)} topics, found {len(items)} fresh item(s).")
    for query, title, link in items:
        msg = build_message(query, title, link)
        critical = is_critical(title)
        send_telegram(msg, pin=critical)


def run_loop():
    seen = load_seen()
    logger.info(f"News alert monitor started. Watching {len(QUERIES)} topics, checking every {CHECK_INTERVAL_SECONDS}s.")

    # Send initial startup confirmation to Telegram
    send_telegram(f"<b>{BOT_LABEL}</b>\n🤖 Bot successfully deployed and running on Render!")

    if not seen:
        logger.info("First run: baselining current headlines (no alerts this pass)...")
        for _, _, _, uid in fetch_all_items():
            if uid:
                seen.add(uid)
        save_seen(seen)

    while True:
        new_items = []
        for query, title, link, uid in fetch_all_items():
            if not uid or uid in seen:
                continue
            seen.add(uid)
            new_items.append((query, title, link))
        if new_items:
            save_seen(seen)
            for query, title, link in new_items:
                msg = build_message(query, title, link)
                critical = is_critical(title)
                send_telegram(msg, pin=critical)
        
        logger.info(f"[heartbeat] Checked {len(QUERIES)} topics, {len(new_items)} new item(s). Next check in {CHECK_INTERVAL_SECONDS // 60} min.")
        time.sleep(CHECK_INTERVAL_SECONDS)


# --- Main Entry Point ------------------------------------------------

if __name__ == "__main__":
    # Start the Flask web server in a separate background thread so Render's health checker is satisfied
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()

    # Execute selected mode
    if "--test" in sys.argv:
        run_test()
    elif "--once" in sys.argv:
        run_once()
    else:
        run_loop()
