# bot.py
import os
import asyncio
import json
import re
import hmac
import hashlib
import html
import random
import xml.etree.ElementTree as ET
from time import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
import asyncpg
import discord
from discord.ext import tasks
from discord.ui import View, button

# ================== CORE CONFIG ==================
GUILD_ID = 1411205177880608831
WELCOME_CHANNEL_ID = 1411946767414591538

# Roles
NEWCOMER_ROLE_ID = 1411957261009555536
MEMBER_ROLE_ID   = 1411938410041708585

# Logs & announcements
MOD_LOG_CHANNEL_ID = 1413297073348018299
LEVEL_UP_ANNOUNCE_CHANNEL_ID = 1415505829401989131

# Season reset announcements
SEASON_RESET_ANNOUNCE_CHANNEL_IDS = [
    1414000088790863874,
    1411931034026643476,
    1411930067994411139,
    1411930091109224479,
    1411930689460240395,
    1414120740327788594,
]

# Reaction Roles
REACTION_CHANNEL_ID = 1414001588091093052
REACTION_ROLE_MAP = {
    "📺": 1412989373556850829,  # Upload Ping
    "🔔": 1412993171670958232,
    "✖️": 1414001344297172992,  # X Ping
    "🎉": 1412992931148595301,
}
RR_STORE_FILE = "reaction_msg.json"

# W/F/L vote channel (auto add 🇼 🇫 🇱)
WFL_CHANNEL_ID = 1411931034026643476

# Counting Channel (only numbers in order)
COUNT_CHANNEL_ID = 1414051875329802320
COUNT_STATE_FILE = "count_state.json"

# Cross-trade detector — MONITOR ALL except these category IDs
CROSS_TRADE_EXCLUDED_CATEGORY_IDS = {
    1411935087867723826,
    1411206110895149127,
    1413998743682023515,
}

# YouTube announce
YT_CHANNEL_ID          = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID        = 1412989373556850829  # Upload Ping
YT_CALLBACK_PATH       = "/yt/webhook"
YT_HUB                 = "https://pubsubhubbub.appspot.com"
YT_SECRET              = "mutapapa-youtube"
YT_CACHE_FILE          = "yt_last_video.json"

# X / Twitter via Nitter/Bridge
X_USERNAME = "Real_Mutapapa"
X_RSS_FALLBACKS = [
    f"https://nitter.net/{X_USERNAME}/rss",
    f"https://nitter.mailt.buzz/{X_USERNAME}/rss",
    f"https://nitter.poast.org/{X_USERNAME}/rss",
]
X_RSS_URL = os.getenv("X_RSS_URL") or X_RSS_FALLBACKS[0]
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_PING_ROLE_ID = 1414001344297172992
X_CACHE_FILE = "x_last_item.json"

# Banner image (set BANNER_URL in environment)
BANNER_URL = os.getenv("BANNER_URL", "").strip()

# Bug review + penalty approvals
BUGS_REVIEW_CHANNEL_ID = 1414124214956593242
PENALTY_CHANNEL_ID     = 1414124795418640535

# Cash drop announcements channel
CASH_DROP_CHANNEL_ID = 1414120740327788594

# Edmonton time
TZ = ZoneInfo("America/Edmonton")

# ================== ECONOMY RULES ==================
EARN_CHANNEL_IDS = [
    1411930638260502638,1411486271464935456,1413297073348018299,1411935203953217566,
    1411435784250331288,1412144563144888452,1411931216608755782,1414000975680897128,
    1411433941403177054,1411931171671117854,1411946767414591538,1413999346592256050,
    1414001588091093052
]
EARN_COOLDOWN_SEC = 180   # 3 minutes
EARN_PER_TICK     = 200
DAILY_CAP         = 2000
DOUBLE_CASH       = False

def tier_bonus(msg_len: int) -> int:
    if msg_len <= 9: return 0
    if msg_len <= 49: return 50
    if msg_len <= 99: return 80
    return 100

# Random drops
DROPS_PER_DAY     = 4
DROP_AMOUNT       = 225
DROP_WORD_COUNT   = 4

# Bug reward
BUG_REWARD_AMOUNT = 350
BUG_REWARD_LIMIT_PER_MONTH = 2

# ================== LEVEL ROLES ==================
ROLE_ROOKIE      = 1414817524557549629
ROLE_SQUAD       = 1414818303028891731
ROLE_SPECIALIST  = 1414818845541138493
ROLE_OPERATIVE   = 1414819588448718880
ROLE_LEGEND      = 1414819897602474057

ACTIVITY_THRESHOLDS = [
    (ROLE_ROOKIE,      5_000),
    (ROLE_SQUAD,      25_000),
    (ROLE_SPECIALIST, 75_000),
    (ROLE_OPERATIVE, 180_000),
    (ROLE_LEGEND,    400_000),
]

HELP_MOD_ROLE_IDS = {1413663966349234320, 1411940485005578322, 1413991410901713088}
NEWCOMER_DAYS = 3

# ================== FILE HELPERS ==================
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
def load_x_cache(): return load_json(X_CACHE_FILE, {})
def save_x_cache(d): save_json(X_CACHE_FILE, d)
def load_yt_cache(): return load_json(YT_CACHE_FILE, {})
def save_yt_cache(d): save_json(YT_CACHE_FILE, d)

# ================== DISCORD CLIENT ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# … (all existing DB setup, giveaways, economy, announcers, loops remain unchanged) …

# ================== MESSAGE HANDLING ==================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").strip()
    clower = content.lower()

    # ---- NEWCOMER LINK BLOCK ----
    if message.guild and any(r.id == NEWCOMER_ROLE_ID for r in message.author.roles):
        if re.search(r"(https?://|discord\\.gg/)", content, re.I):
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.channel.send(
                    f"{message.author.mention} sharing links is not allowed for your role!"
                )
            except Exception:
                pass
            return

    # … (rest of your on_message logic: help, commands, economy, counting, cross-trade, etc.) …

# ================== ANNOUNCERS ==================
async def announce_youtube(video_id: str, title: str):
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(YT_ANNOUNCE_CHANNEL_ID)
    role = guild.get_role(YT_PING_ROLE_ID)
    if not ch or not role: return
    content = f"{title}\n\n{role.mention} Mutapapa just released a new video called: {title}! Click to watch it!"
    embed = discord.Embed(
        title=title or "New upload!",
        url=f"https://youtu.be/{video_id}",
        color=0xE62117
    )
    embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
    try:
        await ch.send(content=content, embed=embed, allowed_mentions=allowed)
        save_yt_cache({"last_video_id": video_id})
    except Exception: pass

async def announce_x(tweet_url: str, title_text: str | None):
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    role = guild.get_role(X_PING_ROLE_ID)
    if not ch or not role: return
    content = f"{role.mention} Mutapapa just posted something on X (Formerly Twitter)! Click to check it out!"
    embed = discord.Embed(
        title=title_text or "New post on X",
        url=tweet_url,
        color=0x1DA1F2
    )
    allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
    try:
        await ch.send(content=content, embed=embed, allowed_mentions=allowed)
        save_x_cache({"last_tweet_id": tweet_url.split('/')[-1]})
    except Exception: pass

# ================== RUN ==================
def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN env var is missing")
    bot.run(token)

if __name__ == "__main__":
    main()