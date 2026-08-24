"""
Breaking Geopolitical News Alert Monitor
-----------------------------------------
Watches Google News for topics you care about (war, attacks, sanctions,
Strait of Hormuz, gold/USD safe-haven moves) and pings you on Telegram the
moment a new matching headline appears.

Two ways to run this:
  1) LOOP mode (for testing on your own PC):
       python news_alert.py
     Runs forever, checking every CHECK_INTERVAL_SECONDS, remembers what
     it already sent in seen_news.json so you don't get duplicates.

  2) ONCE mode (for a cloud Cron Job, e.g. Render):
       python news_alert.py --once
     Runs a single check and exits. Instead of a "seen" file (which won't
     persist on an ephemeral cron container), it only alerts on articles
     published within the last MAX_AGE_MINUTES — so run this on a schedule
     equal to or slightly larger than MAX_AGE_MINUTES and every real story
     gets exactly one alert.

  3) TEST mode (confirm Telegram works before relying on this):
       python news_alert.py --test
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

# --- Config ------------------------------------------------------------
# Credentials are read from environment variables first (recommended for
# cloud deploys), falling back to the values below (handy for local runs).
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8946220251:AAHvtqQRnF2N0deXN91g2RPR--GVR3YB1jQ")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "8776336439")

QUERIES = [
    "news"
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

CHECK_INTERVAL_SECONDS = 900     # loop mode only: how often to poll (15 min)
MAX_AGE_MINUTES = 16             # once mode only: only alert on articles this fresh
                                  # (set this a bit ABOVE your cron interval, e.g.
                                  #  cron runs every 15 min -> MAX_AGE_MINUTES = 16)
SEEN_FILE = "seen_news.json"     # loop mode only
MAX_SEEN_STORED = 3000

BOT_LABEL = "BERLIN NEWS BOT"    # prefix on every message

# If a headline contains any of these (case-insensitive), it's treated as
# CRITICAL: gets a louder header and gets pinned in your Telegram chat.
# Edit this list to match what you consider "very bad" for your trading.
CRITICAL_KEYWORDS = [
    "attack", "strike", "invasion", "invades", "nuclear", "missile",
    "explosion", "airstrike", "bombing", "war declared", "declares war",
    "closes strait", "closure of hormuz", "blocks strait", "blockade",
    "market crash", "flash crash", "emergency", "assassinat", "coup",
    "state of emergency", "military action", "troops deployed",
    "evacuat", "ceasefire collapse", "retaliat",
]

# --- Telegram ------------------------------------------------------------

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
            print("Pin failed:", r.status_code, r.text)
    except Exception as e:
        print("Pin request crashed:", e)


def send_telegram(text, pin=False):
    if not TELEGRAM_BOT_TOKEN or "YOUR_BOT_TOKEN" in TELEGRAM_BOT_TOKEN:
        print("[Telegram not configured] Would have sent:\n", text)
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
            print("Telegram error:", r.status_code, r.text)
            return False
        if pin:
            message_id = r.json().get("result", {}).get("message_id")
            if message_id:
                pin_message(message_id)
        return True
    except Exception as e:
        print("Telegram send failed:", e)
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


# --- Feeds ------------------------------------------------------------

def build_google_news_url(query):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def entry_age_minutes(entry, now_ts):
    if not entry.get("published_parsed"):
        return None
    published_ts = calendar.timegm(entry.published_parsed)
    return (now_ts - published_ts) / 60.0


def fetch_recent_items(max_age_minutes):
    """Stateless fetch: returns items published within max_age_minutes."""
    now_ts = time.time()
    items = []
    for query in QUERIES:
        url = build_google_news_url(query)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Failed to fetch feed for '{query}':", e)
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
    """Used by loop mode: no age filter, dedup via seen_news.json instead."""
    items = []
    for query in QUERIES:
        url = build_google_news_url(query)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Failed to fetch feed for '{query}':", e)
            continue
        for entry in feed.entries[:10]:
            items.append((query, entry.get("title", "No title"), entry.get("link", ""),
                          entry.get("id") or entry.get("link")))
    return items


# --- Modes ------------------------------------------------------------

def run_test():
    print("Sending a test message to Telegram...")
    ok = send_telegram(f"<b>{BOT_LABEL}</b>\n✅ Test message. If you see this, setup is working.")
    print("Sent OK." if ok else "FAILED to send — check your bot token / chat ID.")
    sys.exit(0 if ok else 1)


def run_once():
    items = fetch_recent_items(MAX_AGE_MINUTES)
    print(f"[once] Checked {len(QUERIES)} topics, found {len(items)} fresh item(s).")
    for query, title, link in items:
        msg = build_message(query, title, link)
        critical = is_critical(title)
        print(("[CRITICAL] " if critical else "") + msg)
        send_telegram(msg, pin=critical)


def run_loop():
    seen = load_seen()
    print(f"News alert monitor started. Watching {len(QUERIES)} topics, "
          f"checking every {CHECK_INTERVAL_SECONDS}s.")

    if not seen:
        print("First run: baselining current headlines (no alerts this pass)...")
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
                print(("[CRITICAL] " if critical else "") + msg)
                send_telegram(msg, pin=critical)
        print(f"[heartbeat] Checked {len(QUERIES)} topics, {len(new_items)} new item(s). "
              f"Next check in {CHECK_INTERVAL_SECONDS // 60} min.")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    elif "--once" in sys.argv:
        run_once()
    else:
        run_loop()
