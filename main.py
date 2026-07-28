"""
CryptoPulse Bot — Crypto Price Tracker & Alert Bot
A non-custodial, data-only Telegram bot. No trading, no signals, no financial advice.
Data source: CoinGecko public API (free, no key required).
"""

import os
import sqlite3
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # set this in Railway variables
DB_FILE = "cryptopulse.db"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CHECK_INTERVAL_SECONDS = 60  # how often we poll prices for alerts

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("cryptopulse")

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            coin_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            target_price REAL NOT NULL,
            direction TEXT NOT NULL, -- 'above' or 'below'
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def add_alert(chat_id, coin_id, symbol, target_price, direction):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO alerts (chat_id, coin_id, symbol, target_price, direction, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, coin_id, symbol, target_price, direction, datetime.utcnow().isoformat()),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def get_alerts_for_chat(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, symbol, target_price, direction FROM alerts WHERE chat_id = ?", (chat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_alert(chat_id, alert_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM alerts WHERE chat_id = ? AND id = ?", (chat_id, alert_id))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def get_all_alerts():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, coin_id, symbol, target_price, direction FROM alerts")
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# COINGECKO HELPERS
# ---------------------------------------------------------------------------
_coin_list_cache = None


def get_coin_list():
    """Fetch & cache the full CoinGecko coin list (id, symbol, name)."""
    global _coin_list_cache
    if _coin_list_cache is None:
        resp = requests.get(f"{COINGECKO_BASE}/coins/list", timeout=15)
        resp.raise_for_status()
        _coin_list_cache = resp.json()
    return _coin_list_cache


def resolve_coin_id(user_input):
    """Turn 'btc' or 'bitcoin' into CoinGecko's internal id 'bitcoin'."""
    query = user_input.lower().strip()
    coins = get_coin_list()

    # exact symbol match first (prefer the most well-known coin if duplicates)
    symbol_matches = [c for c in coins if c["symbol"].lower() == query]
    if symbol_matches:
        # crude heuristic: shortest id name is usually the "main" coin
        symbol_matches.sort(key=lambda c: len(c["id"]))
        return symbol_matches[0]["id"], symbol_matches[0]["symbol"].upper()

    # exact id match
    id_matches = [c for c in coins if c["id"] == query]
    if id_matches:
        return id_matches[0]["id"], id_matches[0]["symbol"].upper()

    # exact name match
    name_matches = [c for c in coins if c["name"].lower() == query]
    if name_matches:
        return name_matches[0]["id"], name_matches[0]["symbol"].upper()

    return None, None


def fetch_price(coin_id, vs_currency="usd"):
    resp = requests.get(
        f"{COINGECKO_BASE}/simple/price",
        params={
            "ids": coin_id,
            "vs_currencies": vs_currency,
            "include_24hr_change": "true",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get(coin_id)


def fetch_top_coins(limit=10):
    resp = requests.get(
        f"{COINGECKO_BASE}/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Welcome to CryptoPulse!*\n\n"
        "I track live crypto prices and can ping you the moment a coin hits "
        "your target price — no signup, no wallet connection, nothing to install.\n\n"
        "Try:\n"
        "`/price btc`\n"
        "`/top`\n"
        "`/alert btc 65000 above`\n\n"
        "Type /help to see everything I can do."
    )
    await update.message.reply_markdown(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*CryptoPulse Commands*\n\n"
        "/price `<coin>` — get the live price of a coin\n"
        "  _example:_ `/price eth`\n\n"
        "/top — show the top 10 coins by market cap\n\n"
        "/alert `<coin> <price> <above|below>` — get notified when price crosses your target\n"
        "  _example:_ `/alert btc 65000 above`\n\n"
        "/alerts — list your active alerts\n\n"
        "/delalert `<id>` — remove an alert by its ID\n\n"
        "/about — what this bot does and doesn't do\n\n"
        "_Data is provided by CoinGecko's public API. This bot does not provide "
        "financial advice and does not execute trades._"
    )
    await update.message.reply_markdown(text)


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*About CryptoPulse*\n\n"
        "CryptoPulse is a free price-tracking and alert tool for crypto markets. "
        "It pulls public data from CoinGecko and notifies you when a coin you're "
        "watching crosses a price level you set.\n\n"
        "🔒 We never ask for your wallet, seed phrase, private keys, or any funds.\n"
        "📊 This is a data tool, not financial advice, and not a trading service.\n"
        "🧑‍💻 Built and maintained independently."
    )
    await update.message.reply_markdown(text)


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price <coin>\nExample: /price btc")
        return

    query = context.args[0]
    await update.message.reply_chat_action("typing")

    coin_id, symbol = resolve_coin_id(query)
    if not coin_id:
        await update.message.reply_text(f"❌ Couldn't find a coin matching '{query}'. Check the spelling and try again.")
        return

    try:
        data = fetch_price(coin_id)
    except Exception as e:
        logger.error(f"Price fetch failed: {e}")
        await update.message.reply_text("⚠️ Couldn't fetch price right now. Try again in a moment.")
        return

    if not data:
        await update.message.reply_text("⚠️ No price data found for that coin.")
        return

    price = data.get("usd")
    change = data.get("usd_24h_change", 0)
    arrow = "🟢" if change >= 0 else "🔴"

    text = (
        f"*{symbol}* — ${price:,.4f}\n"
        f"{arrow} 24h change: {change:.2f}%"
    )
    await update.message.reply_markdown(text)


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_chat_action("typing")
    try:
        coins = fetch_top_coins(10)
    except Exception as e:
        logger.error(f"Top coins fetch failed: {e}")
        await update.message.reply_text("⚠️ Couldn't fetch market data right now. Try again shortly.")
        return

    lines = ["*Top 10 Coins by Market Cap*\n"]
    for i, c in enumerate(coins, start=1):
        change = c.get("price_change_percentage_24h") or 0
        arrow = "🟢" if change >= 0 else "🔴"
        lines.append(
            f"{i}. *{c['symbol'].upper()}* — ${c['current_price']:,.2f} {arrow} {change:.2f}%"
        )
    await update.message.reply_markdown("\n".join(lines))


async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /alert <coin> <price> <above|below>\nExample: /alert btc 65000 above"
        )
        return

    coin_query, price_str, direction = context.args[0], context.args[1], context.args[2].lower()

    if direction not in ("above", "below"):
        await update.message.reply_text("Direction must be 'above' or 'below'.")
        return

    try:
        target_price = float(price_str)
    except ValueError:
        await update.message.reply_text("Price must be a number, e.g. 65000")
        return

    coin_id, symbol = resolve_coin_id(coin_query)
    if not coin_id:
        await update.message.reply_text(f"❌ Couldn't find a coin matching '{coin_query}'.")
        return

    chat_id = update.effective_chat.id
    alert_id = add_alert(chat_id, coin_id, symbol, target_price, direction)

    await update.message.reply_markdown(
        f"✅ Alert #{alert_id} set: *{symbol}* {direction} ${target_price:,.2f}\n"
        f"I'll message you the moment it crosses."
    )


async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = get_alerts_for_chat(chat_id)
    if not rows:
        await update.message.reply_text("You have no active alerts. Set one with /alert <coin> <price> <above|below>")
        return

    lines = ["*Your Active Alerts*\n"]
    for alert_id, symbol, target_price, direction in rows:
        lines.append(f"#{alert_id} — {symbol} {direction} ${target_price:,.2f}")
    lines.append("\nRemove one with /delalert <id>")
    await update.message.reply_markdown("\n".join(lines))


async def delalert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delalert <id>")
        return
    try:
        alert_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Alert ID must be a number. Check /alerts for your IDs.")
        return

    chat_id = update.effective_chat.id
    deleted = delete_alert(chat_id, alert_id)
    if deleted:
        await update.message.reply_text(f"🗑️ Alert #{alert_id} removed.")
    else:
        await update.message.reply_text("Couldn't find that alert ID under your account.")


# ---------------------------------------------------------------------------
# BACKGROUND JOB — checks all alerts periodically
# ---------------------------------------------------------------------------
async def check_alerts_job(context: ContextTypes.DEFAULT_TYPE):
    rows = get_all_alerts()
    if not rows:
        return

    # group by coin_id to minimize API calls
    coin_ids = list({r[2] for r in rows})
    prices = {}
    for cid in coin_ids:
        try:
            data = fetch_price(cid)
            if data:
                prices[cid] = data.get("usd")
        except Exception as e:
            logger.error(f"Alert check price fetch failed for {cid}: {e}")

    for alert_id, chat_id, coin_id, symbol, target_price, direction in rows:
        current = prices.get(coin_id)
        if current is None:
            continue

        triggered = (direction == "above" and current >= target_price) or (
            direction == "below" and current <= target_price
        )

        if triggered:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔔 *Alert Triggered!*\n"
                        f"{symbol} is now ${current:,.2f} ({direction} your target of ${target_price:,.2f})"
                    ),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
            delete_alert(chat_id, alert_id)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alerts", alerts_cmd))
    app.add_handler(CommandHandler("delalert", delalert_cmd))

    # background job to check alerts every CHECK_INTERVAL_SECONDS
    app.job_queue.run_repeating(check_alerts_job, interval=CHECK_INTERVAL_SECONDS, first=10)

    logger.info("CryptoPulse bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
