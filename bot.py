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

# ================== CORE CONFIG (edit IDs) ==================
# ================== CORE CONFIG ==================
GUILD_ID = 1411205177880608831

WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID   = 1411957261009555536
MEMBER_ROLE_ID     = 1411938410041708585

# Roles
NEWCOMER_ROLE_ID = 1411957261009555536
MEMBER_ROLE_ID   = 1411938410041708585

# Logs & announcements
MOD_LOG_CHANNEL_ID = 1413297073348018299
LEVEL_UP_ANNOUNCE_CHANNEL_ID = 1415505829401989131

# Level-up announcements
LEVEL_UP_CHANNEL_ID = 1415505829401989131
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
    "✖️": 1414001344297172992,  # X Ping (also used below)
    "🎉": 1412992931148595301,
}
RR_STORE_FILE = "reaction_msg.json"
@@ -48,14 +60,14 @@
COUNT_CHANNEL_ID = 1414051875329802320
COUNT_STATE_FILE = "count_state.json"

# Categories to IGNORE for cross-trade detector
CROSSTRADE_EXCLUDED_CATEGORY_IDS = {
# Cross-trade detector — MONITOR ALL except these category IDs
CROSS_TRADE_EXCLUDED_CATEGORY_IDS = {
    1411935087867723826,
    1411206110895149127,
    1413998743682023515,
}

# YouTube (WebSub push + poll fallback)
# YouTube announce
YT_CHANNEL_ID          = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID        = 1412989373556850829  # Upload Ping
@@ -64,42 +76,28 @@
YT_SECRET              = "mutapapa-youtube"
YT_CACHE_FILE          = "yt_last_video.json"

# X / Twitter
# X / Twitter via Nitter/Bridge
X_USERNAME = "Real_Mutapapa"
X_PING_ROLE_ID = 1414001344297172992  # X Ping
X_RSS_FALLBACKS = [
    f"https://nitter.net/{X_USERNAME}/rss",
    f"https://nitter.mailt.buzz/{X_USERNAME}/rss",
    f"https://nitter.poast.org/{X_USERNAME}/rss",
]
X_RSS_URL = os.getenv("X_RSS_URL") or X_RSS_FALLBACKS[0]
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_PING_ROLE_ID = 1414001344297172992  # X Ping
X_CACHE_FILE = "x_last_item.json"

# Banner (replace with your public URL of the image you uploaded)
BANNER_URL = os.getenv("BANNER_URL", "PUT_A_PUBLIC_IMAGE_URL_HERE")
# Banner image (set BANNER_URL in environment)
BANNER_URL = os.getenv("BANNER_URL", "").strip()

# Bug review + rule-break penalty approvals
# Bug review + penalty approvals
BUGS_REVIEW_CHANNEL_ID = 1414124214956593242
PENALTY_CHANNEL_ID     = 1414124795418640535  # rule-break penalty confirm buttons

# Cash drop announcements channel
CASH_DROP_CHANNEL_ID = 1414120740327788594

# Season reset announce channels
SEASON_RESET_ANNOUNCE_CHANNEL_IDS = [
    1414000088790863874,
    1411931034026643476,
    1411930067994411139,
    1411930091109224479,
    1411930689460240395,
    1414120740327788594,
]

# Helpful channels
CASH_ANNOUNCE_CHANNEL_ID = 1414124134903844936
LEADERBOARD_CHANNEL_ID   = 1414124214956593242

# Edmonton time
TZ = ZoneInfo("America/Edmonton")

@@ -121,15 +119,16 @@
    if msg_len <= 99: return 80
    return 100

# Random drop scheduler (3 or 4 per day at random times)
# Random drops (scheduled, plus manual !cash drop)
DROPS_PER_DAY     = 4
DROP_AMOUNT       = 225
DROP_WORD_COUNT   = 4

# Bug reward
BUG_REWARD_AMOUNT = 350
BUG_REWARD_LIMIT_PER_MONTH = 2

# ================== LEVEL ROLES ==================
# ================== LEVEL ROLES (activity-based) ==================
ROLE_ROOKIE      = 1414817524557549629
ROLE_SQUAD       = 1414818303028891731
ROLE_SPECIALIST  = 1414818845541138493
@@ -144,13 +143,17 @@
    (ROLE_LEGEND,    400_000),
}

# Roles that can see & use mod-only commands (plus anyone with Manage Messages)
# Help embed: show mod section only if user has these roles or admin
HELP_MOD_ROLE_IDS = {1413663966349234320, 1411940485005578322, 1413991410901713088}

# ================== PERSIST HELPERS ==================
CONFIG_FILE   = "config.json"
GIVEAWAYS_FILE = "giveaways.json"
COUNT_STATE_FILE = "count_state.json"
# Newcomer -> Member after 3 days
NEWCOMER_DAYS = 3

# ================== FILE PERSIST HELPERS ==================
CONFIG_FILE     = "config.json"
GIVEAWAYS_FILE  = "giveaways.json"
COUNT_STATE     = {}
GIVEAWAYS       = {}

def load_json(path, default):
    try:
@@ -166,30 +169,42 @@
def load_config():
    return load_json(CONFIG_FILE, {"age_gate_enabled": True, "min_account_age_sec": 7 * 24 * 3600})

def save_config(cfg): save_json(CONFIG_FILE, cfg)
def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def load_rr_store():
    return load_json(RR_STORE_FILE, {})

def save_rr_store(d):
    save_json(RR_STORE_FILE, d)

def load_rr_store(): return load_json(RR_STORE_FILE, {})
def save_rr_store(d): save_json(RR_STORE_FILE, d)
def load_x_cache():
    return load_json(X_CACHE_FILE, {})

def load_x_cache(): return load_json(X_CACHE_FILE, {})
def save_x_cache(d): save_json(X_CACHE_FILE, d)
def save_x_cache(d):
    save_json(X_CACHE_FILE, d)

def load_yt_cache(): return load_json(YT_CACHE_FILE, {})
def save_yt_cache(d): save_json(YT_CACHE_FILE, d)
def load_yt_cache():
    return load_json(YT_CACHE_FILE, {})

def save_yt_cache(d):
    save_json(YT_CACHE_FILE, d)

def load_count_state():
    d = load_json(COUNT_STATE_FILE, {"expected_next": 1, "goal": 67})
    d.setdefault("expected_next", 1)
    d.setdefault("goal", 67)
    return d

def save_count_state(d): save_json(COUNT_STATE_FILE, d)
def save_count_state(d):
    save_json(COUNT_STATE_FILE, d)

def load_giveaways():
    data = load_json(GIVEAWAYS_FILE, {})
    return data if isinstance(data, dict) else {}

def save_giveaways(d): save_json(GIVEAWAYS_FILE, d)
def save_giveaways(d):
    save_json(GIVEAWAYS_FILE, d)

CONFIG      = load_config()
COUNT_STATE = load_count_state()
@@ -218,15 +233,12 @@
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)

    async with _pool.acquire() as con:
        # meta
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        (;""")

        # users
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_users (
            user_id BIGINT PRIMARY KEY,
@@ -235,12 +247,8 @@
            today_earned BIGINT NOT NULL DEFAULT 0,
            bug_rewards_this_month INTEGER NOT NULL DEFAULT 0,
            activity_points BIGINT NOT NULL DEFAULT 0
        );
        """)
        await con.execute("ALTER TABLE muta_users ADD COLUMN IF NOT EXISTS activity_points BIGINT NOT NULL DEFAULT 0;")
        await con.execute("ALTER TABLE muta_users ADD COLUMN IF NOT EXISTS today_earned BIGINT NOT NULL DEFAULT 0;")
        );""")

        # drops
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_drops (
            id BIGSERIAL PRIMARY KEY,
@@ -251,8 +259,8 @@
            claimed_by BIGINT,
            claimed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        );""")

        await con.execute("CREATE INDEX IF NOT EXISTS idx_muta_drops_created_at ON muta_drops (created_at);")

async def db_fetchrow(query, *args):
@@ -305,38 +313,19 @@
        ns = {"atom":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return web.Response(text="no entry")
            return web.Response(text="ok")
        vid = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title", default="", namespaces=ns)
    except Exception as e:
        print(f"[yt-webhook] parse error: {e}")
        return web.Response(text="ok")

    if vid:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            ch = guild.get_channel(YT_ANNOUNCE_CHANNEL_ID)
            role = guild.get_role(YT_PING_ROLE_ID)
            if ch and role:
                # EXACT format you asked for
                try:
                    await ch.send(f"{title}\n\n{role.mention} Mutapapa just released a new video called: {title} Click to watch it!")
                except Exception:
                    pass
                embed = discord.Embed(
                    title=title or "New upload!",
                    url=f"https://youtu.be/{vid}",
                    description="",
                    color=0xE62117
                )
                embed.set_image(url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
                await ch.send(embed=embed)
                save_yt_cache({"last_video_id": vid})
                print(f"[yt-webhook] announced {vid}")

    if vid and title:
        await announce_youtube(vid, title)
    return web.Response(text="ok")

async def health(_): return web.Response(text="ok")
async def health(_):
    return web.Response(text="ok")

app.add_routes([
    web.get(YT_CALLBACK_PATH, yt_webhook_handler),
@@ -353,44 +342,18 @@
    await site.start()
    print(f"[yt-webhook] listening on 0.0.0.0:{port}{YT_CALLBACK_PATH}")

# Poll fallback for YouTube in case WebSub is flaky
@tasks.loop(minutes=3)
async def yt_poll_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(YT_ANNOUNCE_CHANNEL_ID)
    role = guild.get_role(YT_PING_ROLE_ID)
    if not ch or not role:
        return

    cache = load_yt_cache()
    last_vid = cache.get("last_video_id")

    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"
async def websub_subscribe(public_base_url: str):
    topic = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"
    callback = f"{public_base_url.rstrip('/')}{YT_CALLBACK_PATH}"
    data = {"hub.mode":"subscribe","hub.topic":topic,"hub.callback":callback,"hub.verify":"async"}
    if YT_SECRET:
        data["hub.secret"] = YT_SECRET
    try:
        async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as session:
            async with session.get(feed_url, timeout=10) as resp:
                if resp.status != 200:
                    return
                xml = await resp.text()
        root = ET.fromstring(xml)
        ns = {"atom":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return
        vid = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title", default="", namespaces=ns)
        if not vid or vid == last_vid:
            return

        await ch.send(f"{title}\n\n{role.mention} Mutapapa just released a new video called: {title} Click to watch it!")
        embed = discord.Embed(title=title or "New upload!", url=f"https://youtu.be/{vid}", color=0xE62117)
        embed.set_image(url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
        await ch.send(embed=embed)
        save_yt_cache({"last_video_id": vid})
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{YT_HUB}/subscribe", data=data, timeout=10) as resp:
                print(f"[yt-webhook] subscribe {resp.status} -> {callback}")
    except Exception as e:
        print(f"[yt-poll] error: {e}")
        print(f"[yt-webhook] subscribe error: {e}")

# ================== GIVEAWAYS ==================
class GiveawayView(View):
@@ -447,6 +410,7 @@
        gw["ended"] = True
        save_giveaways(GIVEAWAYS)
        return

    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
@@ -470,10 +434,8 @@
        item.disabled = True

    if msg:
        try:
            await msg.edit(embed=embed, view=view)
        except Exception:
            pass
        try: await msg.edit(embed=embed, view=view)
        except Exception: pass

    try:
        if winners:
@@ -496,7 +458,10 @@

async def add_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("UPDATE muta_users SET cash = cash + $1 WHERE user_id=$2 RETURNING cash", amount, uid)
    row = await db_fetchrow(
        "UPDATE muta_users SET cash = cash + $1 WHERE user_id=$2 RETURNING cash",
        amount, uid
    )
    return int(row["cash"]) if row else 0

async def deduct_cash(uid: int, amount: int) -> int:
@@ -520,7 +485,10 @@

async def mark_bug_reward(uid: int):
    await ensure_user(uid)
    await db_execute("UPDATE muta_users SET bug_rewards_this_month = bug_rewards_this_month + 1 WHERE user_id=$1", uid)
    await db_execute(
        "UPDATE muta_users SET bug_rewards_this_month = bug_rewards_this_month + 1 WHERE user_id=$1",
        uid
    )

async def leaderboard_top(n: int = 10):
    return await db_fetch("SELECT user_id, cash FROM muta_users ORDER BY cash DESC LIMIT $1", n)
@@ -551,33 +519,30 @@
    return n*24*3600 if unit=="d" else n*3600 if unit=="h" else n*60

async def assign_activity_roles(member: discord.Member, points: int):
    """Grant roles for which the member qualifies; announce in level-up channel (no role pings)."""
    if not member or not member.guild:
        return
    granted_names = []
    to_grant = []
    granted = []
    for role_id, threshold in ACTIVITY_THRESHOLDS:
        if role_id and points >= threshold:
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                to_grant.append(role)
                granted_names.append(role.name)
    if to_grant:
                granted.append(role)

    if granted:
        try:
            await member.add_roles(*to_grant, reason=f"Reached activity thresholds (points={points})")
            await member.add_roles(*granted, reason=f"Reached activity thresholds (points={points})")
        except Exception as e:
            print(f"[levels] add_roles error: {e}")
        # announce
        ch = member.guild.get_channel(LEVEL_UP_CHANNEL_ID)
        if ch and granted_names:
        # announce highest newly-granted role
        top_role = granted[-1]
        ch = member.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
        if ch:
            try:
                # show highest one granted this tick
                await ch.send(f"{member.mention} reached the **{granted_names[-1]}** role!")
                await ch.send(f"{member.mention} reached the **{top_role.name}** role! 🎉")
            except Exception:
                pass

async def earn_for_message(uid: int, now: datetime, msg_len: int, guild: discord.Guild | None, author_id: int):
    """Earning logic for normal messages. Also increments activity_points and handles auto-roles."""
    await ensure_user(uid)

    row = await db_fetchrow("SELECT cash, last_earn_ts, today_earned, activity_points FROM muta_users WHERE user_id=$1", uid)
@@ -601,9 +566,9 @@
        base *= 2

    grant = min(base, max(0, DAILY_CAP - today_earned))

    new_today = today_earned + grant
    new_points = activity_points + grant

    await db_execute(
        "UPDATE muta_users SET cash = cash + $1, last_earn_ts = $2, today_earned = $3, activity_points = $4 WHERE user_id=$5",
        grant, now, new_today, new_points, uid
@@ -636,20 +601,34 @@
    re.compile(r"\b(pp|paypal|btc|eth|cashapp|venmo)\b", re.I),
]

# ================== X helpers / announcer ==================
# ================== X helpers ==================
_TWEET_ID_RE = re.compile(r"/status/(\d+)")

def _extract_tweet_id(link: str) -> str | None:
    m = _TWEET_ID_RE.search(link or "")
    return m.group(1) if m else None

def nitter_to_x(url: str) -> str:
    return url.replace("https://nitter.net", "https://x.com")

TWEET_LINK_RE = re.compile(r"/" + re.escape(X_USERNAME) + r"/status/(\d+)")

def nitter_latest_id_from_html(text: str) -> str | None:
    m = TWEET_LINK_RE.search(text)
    return m.group(1) if m else None

def nitter_to_x(url: str) -> str:
    return url.replace("https://nitter.net", "https://x.com")

def four_words():
    words = ["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly",
             "kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango",
             "ultra","vivid","wax","xeno","yodel","zen"]
    return " ".join(random.choice(words) for _ in range(DROP_WORD_COUNT))

async def try_delete(msg: discord.Message):
    try:
        await msg.delete()
    except Exception:
        pass

# ================== VIEWS (Penalty + Bug Approvals) ==================
class PenaltyView(View):
    def __init__(self, target_id: int, amount: int):
@@ -698,15 +677,8 @@
        await interaction.response.edit_message(content="Bug report rejected.", view=None)

# ================== HELP / COMMANDS EMBED ==================
def is_mod(member: discord.Member) -> bool:
    if not member or not hasattr(member, "guild_permissions"):
        return False
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
        return True
    return any((r.id in HELP_MOD_ROLE_IDS) for r in getattr(member, "roles", []))

def build_commands_embed(author: discord.Member) -> discord.Embed:
    show_mod = is_mod(author)
    show_mod = any((r.id in HELP_MOD_ROLE_IDS) for r in getattr(author, "roles", [])) or getattr(author.guild_permissions, "administrator", False)

    embed = discord.Embed(
        title="📜 Mutapapa Bot Commands",
@@ -715,131 +687,119 @@
    )

    everyone = [
        ("!balance | !bal | !cashme | !mycash", "See how much Mutapapa Cash you have (it pings you)."),
        ("!leaderboard", "Shows the Top 10 richest users on the server."),
        ("!ping", "Check if the bot is alive. Responds with 'pong 🏓'."),
        ("!balance | !bal | !cashme | !mycash", "See your cash balance (the bot pings you)."),
        ("!leaderboard", "Shows the Top 10 richest users."),
        (f"!cash <{DROP_WORD_COUNT} words>", "Claim a **cash drop** when it appears. Example: `!cash alpha bravo charlie delta`."),
        ("!bugreport <description>", f"Report a Jailbreak bug. If approved by mods, you earn **{BUG_REWARD_AMOUNT} cash** (max {BUG_REWARD_LIMIT_PER_MONTH}/month)."),
        ("!bugreport <description>", f"Report a Jailbreak bug. If approved, you get **{BUG_REWARD_AMOUNT}** cash (max {BUG_REWARD_LIMIT_PER_MONTH}/month)."),
        ("!countstatus", "Check the counting game progress (next number & goal)."),
    ]
    ev_lines = [f"**{name}**\n{desc}" for name, desc in everyone]
    embed.add_field(name="👥 Everyone", value="\n\n".join(ev_lines), inline=False)

    if show_mod:
        admin = [
            ("!ping", "Health check (mods only)."),
            ("!countstatus", "Show counting progress (mods only)."),
            ("!send <message>", "Make the bot send a message as itself."),
            ("!sendreact <message>", "Post to the reaction-role channel and auto-add 📺 🔔 ✖️ 🎉."),
            ("!gstart <duration> | <winners> | <title> | <desc>", "Start a giveaway. Example: `!gstart 1h | 1 | 100 Robux | Join now!`"),
            ("!gend", "End the most recent active giveaway."),
            ("!greroll", "Reroll the most recent giveaway."),
            ("!countgoal <n>", "Set counting goal."),
            ("!countnext <n>", "Force next expected number."),
            ("!countreset", "Reset counting to 1."),
            ("!doublecash on|off", "Toggle double-cash earnings."),
            ("!addcash @user <amount> [reason] | !add ...", "Give cash."),
            ("!removecash @user <amount> [reason] | !remove ...", "Remove cash."),
            ("!cashdrop", "Create an immediate cash drop in the cash-drop channel."),
            ("!levelup @user <rookie|squad|specialist|operative|legend>", "Force-promote user to a level role & announce."),
            ("!delete", "Delete the bot’s most recent message in this channel (works in DMs too)."),
            ("!send <message>", "Bot sends a message as itself."),
            ("!sendreact <message>", "Post a reaction-role message in the reaction channel (auto-add 📺 🔔 ✖️ 🎉)."),
            ("!gstart <duration> | <winners> | <title> | <desc>", "Start a giveaway. Examples:\n`!gstart 1h | 1 | 100 Robux | Join now!`\n`!gstart 0h 1m | 1 | Flash Drop | Hurry!`"),
            ("!gend", "Ends the most recent active giveaway."),
            ("!greroll", "Rerolls the most recent giveaway."),
            ("!countgoal <number>", "Set the counting goal."),
            ("!countnext <number>", "Force the next expected number."),
            ("!countreset", "Reset counting back to 1."),
            ("!doublecash on|off", "Turn double-cash on or off."),
            ("!addcash @user <amount> [reason] | !add ...", "Give cash to a user."),
            ("!removecash @user <amount> [reason] | !remove ...", "Remove cash from a user."),
            ("!levelup @user <Rookie|Squad|Specialist|Operative|Legend>", "Force-promote a user to a level role (announces it)."),
            ("!cash drop [amount]", "Manually create a cash drop (default amount is 225)."),
            ("!delete", "Delete my most recent message in this channel (works in DMs too)."),
        ]
        ad_lines = [f"**{name}**\n{desc}" for name, desc in admin]
        embed.add_field(name="🛠️ Admin / Mods", value="\n\n".join(ad_lines), inline=False)

    return embed

# ================== BACKGROUND LOOPS ==================
@tasks.loop(seconds=45)
async def drops_loop():
    """Create drops only at scheduled random times (3–4 per local day)."""
# ================== ANNOUNCERS ==================
async def announce_youtube(video_id: str, title: str):
    """Announce a new YT video with your exact phrasing & Upload Ping role."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch:
    ch = guild.get_channel(YT_ANNOUNCE_CHANNEL_ID)
    role = guild.get_role(YT_PING_ROLE_ID)
    if not ch or not role:
        return

    # Ensure table exists
    # First line Title, then the ping + sentence
    content = f"{title}\n\n{role.mention} Mutapapa just released a new video called: {title}! Click to watch it!"
    embed = discord.Embed(
        title=title or "New upload!",
        url=f"https://youtu.be/{video_id}",  # works for Shorts too
        description="",
        color=0xE62117
    )
    embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
    try:
        await db_execute("""
        CREATE TABLE IF NOT EXISTS muta_drops (
            id BIGSERIAL PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL UNIQUE,
            phrase TEXT NOT NULL,
            amount INTEGER NOT NULL,
            claimed_by BIGINT,
            claimed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
    except Exception:
        return

    now = datetime.now(tz=TZ)
    day_key = now.strftime("%Y%m%d")
    meta_key = f"drops_schedule:{day_key}"
    raw = await db_get_meta(meta_key)
    schedule = None
    if raw:
        try:
            schedule = json.loads(raw)
        except Exception:
            schedule = None
    if not schedule or "times" not in schedule or "created" not in schedule:
        start = datetime(now.year, now.month, now.day, tzinfo=TZ)
        end   = start + timedelta(days=1)
        count = random.choice([3, 4])
        seconds = sorted(random.sample(range(int((end - start).total_seconds())), count))
        times = [int(start.timestamp()) + s for s in seconds]
        schedule = {"times": times, "created": [False]*count}
        await db_set_meta(meta_key, json.dumps(schedule))

    for i, ts in enumerate(schedule["times"]):
        if schedule["created"][i]:
            continue
        if time() >= ts:
            words = ["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly",
                     "kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango",
                     "ultra","vivid","wax","xeno","yodel","zen"]
            phrase = " ".join(random.choice(words) for _ in range(DROP_WORD_COUNT))
            embed = discord.Embed(
                title="[Cash] Cash drop!",
                description=f"Type `!cash {phrase}` to collect **{DROP_AMOUNT}** cash!",
                color=0x2ECC71
            )
            try:
                msg = await ch.send(embed=embed)
            except Exception:
                return

            try:
                await db_execute("""
                    INSERT INTO muta_drops(channel_id, message_id, phrase, amount, created_at)
                    VALUES($1,$2,$3,$4, NOW())
                """, CASH_DROP_CHANNEL_ID, msg.id, phrase.lower(), DROP_AMOUNT)
                schedule["created"][i] = True
                await db_set_meta(meta_key, json.dumps(schedule))
            except Exception:
                try: await msg.delete()
                except Exception: pass
            finally:
                break  # one per loop
        await ch.send(content=content, embed=embed, allowed_mentions=allowed)
        save_yt_cache({"last_video_id": video_id})
    except Exception as e:
        print(f"[yt-announce] send error: {e}")

@tasks.loop(minutes=2)
async def x_posts_loop():
    """Announce only brand-new tweets; exact wording; no duplicates."""
async def announce_x(tweet_url: str, title_text: str | None):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    role = guild.get_role(X_PING_ROLE_ID)
    if not ch:
    if not ch or not role:
        return
    content = f"{role.mention} Mutapapa just posted something on X (Formerly Twitter)! Click to check it out!"
    embed = discord.Embed(
        title=title_text or "New post on X",
        url=tweet_url,
        description="",
        color=0x1DA1F2
    )
    allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
    try:
        await ch.send(content=content, embed=embed, allowed_mentions=allowed)
    except Exception:
        pass

# ================== BACKGROUND LOOPS ==================
@tasks.loop(minutes=3)
async def yt_poll_loop():
    """Poll the YouTube feed as a fallback (in case WebSub doesn’t hit)."""
    cache = load_yt_cache()
    last_vid = cache.get("last_video_id")
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as session:
            async with session.get(feed_url, timeout=10) as resp:
                if resp.status != 200:
                    return
                xml = await resp.text()
        root = ET.fromstring(xml)
        ns = {"atom":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return
        vid = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title", default="", namespaces=ns)
        if not vid or vid == last_vid:
            return
        await announce_youtube(vid, title or "New upload!")
    except Exception as e:
        print(f"[yt-poll] error: {e}")

@tasks.loop(minutes=2)
async def x_posts_loop():
    """Announce only brand-new tweets by storing the last tweet ID."""
    cache = load_x_cache()
    last_tweet_id = cache.get("last_tweet_id")

    # RSS first
    # 1) Try RSS first
    feeds = [X_RSS_URL] + [u for u in X_RSS_FALLBACKS if u != X_RSS_URL]
    try:
        xml = None
@@ -865,21 +825,15 @@
                    tweet_id = _extract_tweet_id(link)
                    if tweet_id and tweet_id != last_tweet_id:
                        x_link = nitter_to_x(link) if link else f"https://x.com/{X_USERNAME}/status/{tweet_id}"
                        # EXACT wording
                        if role:
                            await ch.send(f"{title}\n\n{role.mention} Mutapapa just posted something on X (Formerly Twitter)!  Click to check it out!")
                        else:
                            await ch.send(f"{title}\n\nMutapapa just posted something on X (Formerly Twitter)!  Click to check it out!")
                        embed = discord.Embed(title="", url=x_link, color=0x1DA1F2)
                        await ch.send(embed=embed)
                        await announce_x(x_link, title)
                        save_x_cache({"last_tweet_id": tweet_id})
                        return
            except Exception:
                pass
    except Exception:
        pass

    # Fallback parse
    # 2) Fallback: Nitter HTML via r.jina.ai — only post if tweet_id changed
    try:
        mirror_url = f"https://r.jina.ai/http://nitter.net/{X_USERNAME}"
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
@@ -895,23 +849,80 @@
        return

    x_link = f"https://x.com/{X_USERNAME}/status/{tweet_id}"
    if role:
        await ch.send(f"New post on X\n\n{role.mention} Mutapapa just posted something on X (Formerly Twitter)!  Click to check it out!")
    else:
        await ch.send(f"New post on X\n\nMutapapa just posted something on X (Formerly Twitter)!  Click to check it out!")
    await ch.send(embed=discord.Embed(url=x_link, color=0x1DA1F2))
    await announce_x(x_link, "New post on X")
    save_x_cache({"last_tweet_id": tweet_id})

# Random drop scheduler (persisted schedule so they’re truly random across the day)
def _today_key(now: datetime) -> str:
    return now.strftime("%Y%m%d")

async def _get_or_build_today_drop_schedule(now: datetime) -> dict:
    day_key = _today_key(now)
    meta_key = f"drops_schedule:{day_key}"
    raw = await db_get_meta(meta_key)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "times" in data and "created" in data:
                return data
        except Exception:
            pass
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    end   = start + timedelta(days=1)
    count = random.choice([3, 4])
    seconds = sorted(random.sample(range(int((end - start).total_seconds())), count))
    times = [int(start.timestamp()) + s for s in seconds]
    schedule = {"times": times, "created": [False]*count}
    await db_set_meta(meta_key, json.dumps(schedule))
    return schedule

async def _mark_drop_created(now: datetime, schedule: dict, idx: int):
    schedule["created"][idx] = True
    meta_key = f"drops_schedule:{_today_key(now)}"
    await db_set_meta(meta_key, json.dumps(schedule))

@tasks.loop(seconds=45)
async def drops_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch:
        return

    now = datetime.now(tz=TZ)
    schedule = await _get_or_build_today_drop_schedule(now)
    for i, ts in enumerate(schedule["times"]):
        if schedule["created"][i]:
            continue
        if time() >= ts:
            phrase = four_words()
            embed = discord.Embed(
                title="[Cash] Cash drop!",
                description=f"Type `!cash {phrase}` to collect **{DROP_AMOUNT}** cash!",
                color=0x2ECC71
            )
            try:
                msg = await ch.send(embed=embed)
                await db_execute("""
                    INSERT INTO muta_drops(channel_id, message_id, phrase, amount, created_at)
                    VALUES($1,$2,$3,$4, NOW())
                """, CASH_DROP_CHANNEL_ID, msg.id, phrase.lower(), DROP_AMOUNT)
                await _mark_drop_created(now, schedule, i)
            except Exception:
                try: await msg.delete()
                except Exception: pass
            finally:
                break

@tasks.loop(minutes=1)
async def monthly_reset_loop():
    """Reset ONLY at the end of the month: last day 23:59 America/Edmonton."""
    now = datetime.now(tz=TZ)
    next_minute = now + timedelta(minutes=1)
    if now.hour == 23 and now.minute == 59 and next_minute.day == 1:
        print("[season] monthly reset running…")
        rows = await leaderboard_top(10)
        await monthly_reset()

        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
@@ -923,8 +934,7 @@
                    )
                for cid in SEASON_RESET_ANNOUNCE_CHANNEL_IDS:
                    ch = guild.get_channel(cid)
                    if not ch:
                        continue
                    if not ch: continue
                    if desc:
                        embed = discord.Embed(
                            title="🏁 Season ended — Final Top 10",
@@ -936,99 +946,104 @@
        except Exception:
            pass

# ================== EVENTS ==================
@tasks.loop(minutes=10)
async def newcomer_promote_loop():
    """Promote users from NEWCOMER to MEMBER after 3 days in guild."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    newcomer_role = guild.get_role(NEWCOMER_ROLE_ID)
    member_role   = guild.get_role(MEMBER_ROLE_ID)
    if not newcomer_role or not member_role:
        return
    now = datetime.now(tz=TZ)
    for m in guild.members:
        if newcomer_role in m.roles:
            joined = m.joined_at.astimezone(TZ) if m.joined_at else None
            if joined and (now - joined) >= timedelta(days=NEWCOMER_DAYS):
                try:
                    await m.remove_roles(newcomer_role, reason="Auto promotion window passed")
                    await m.add_roles(member_role, reason="Auto promotion after 3 days")
                except Exception as e:
                    print(f"[promote] role error: {e}")

# ================== DISCORD EVENTS ==================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await db_init()
    await start_webserver()
    yt_poll_loop.start()
    drops_loop.start()
    x_posts_loop.start()
    monthly_reset_loop.start()

# ================== MESSAGE HANDLING ==================
def four_words():
    words = ["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly",
             "kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango",
             "ultra","vivid","wax","xeno","yodel","zen"]
    return " ".join(random.choice(words) for _ in range(DROP_WORD_COUNT))

async def try_delete(msg: discord.Message):
    try: await msg.delete()
    except Exception: pass
    # start background loops once
    for loop_obj in (yt_poll_loop, x_posts_loop, drops_loop, monthly_reset_loop, newcomer_promote_loop):
        if not loop_obj.is_running():
            loop_obj.start()

# ================== MESSAGE HANDLING ==================
@bot.event
async def on_message(message: discord.Message):
    # DMs: only allow !delete, !ping (for sanity), !help
    is_dm = isinstance(message.channel, (discord.DMChannel, discord.GroupChannel))
    # allow DM commands for !delete and !ping behavior
    in_guild = message.guild is not None
    if message.author.bot:
        return

    content = (message.content or "").strip()
    clower  = content.lower()

    # ---------------- HELP ----------------
    if clower in ("!commands", "!help"):
        # show guild-aware help if available; in DM show everyone section only
        if message.guild:
            await message.channel.send(embed=build_commands_embed(message.author))
        else:
            # DM help
            embed = discord.Embed(title="📜 Mutapapa Bot Commands", color=0x5865F2)
            embed.add_field(
                name="DM commands",
                value="`!delete` — deletes my last DM message to you\n`!help` — this message",
                inline=False
            )
            await message.channel.send(embed=embed)
        try: await message.delete()
        except Exception: pass
    async def delete_command_msg():
        try:
            await message.delete()
        except Exception:
            pass

    # ---------- HELP ----------
    if in_guild and clower in ("!commands", "!help"):
        await message.channel.send(embed=build_commands_embed(message.author))
        await delete_command_msg()
        return

    # From here: guild & DMs diverge for permissions
    # ---------------- DMs ----------------
    if is_dm:
        if clower == "!ping":
    # ---------- BASIC ----------
    if clower == "!ping":
        # respond in DMs or guild
        try:
            await message.channel.send("pong 🏓")
            await try_delete(message)
            return
        if clower == "!delete":
            # delete bot’s last message in this DM
            async for m in message.channel.history(limit=20):
                if m.author.id == (bot.user.id if bot.user else 0):
                    await try_delete(m)
                    break
            await try_delete(message)
            return
        return  # ignore other commands in DMs

    # ---------------- GUILD ONLY BELOW ----------------
    guild = message.guild

    def require_mod() -> bool:
        return is_mod(message.author)

    async def delete_command_msg():
        try: await message.delete()
        except Exception: pass
        except Exception:
            pass
        await delete_command_msg()
        return

    # ---------- MOD-ONLY ----------
    if clower == "!ping":
        if not require_mod(): return
        await message.channel.send("pong 🏓")
    def is_mod_or_admin(member: discord.Member | None) -> bool:
        if not member: return False
        if member.guild_permissions.administrator: return True
        return any((r.id in HELP_MOD_ROLE_IDS) for r in member.roles)

    # !delete — delete bot's most recent message in this channel/DM
    if clower == "!delete":
        # Only mods in guild; in DMs allow anyone to delete bot's recent message to them
        if in_guild and not is_mod_or_admin(message.author):
            await delete_command_msg()
            return
        try:
            last = None
            async for m in message.channel.history(limit=50):
                if m.author.id == bot.user.id:
                    last = m; break
            if last:
                await last.delete()
        except Exception:
            pass
        await delete_command_msg()
        return

    if clower == "!countstatus":
        if not require_mod(): return
        st = COUNT_STATE
        await message.channel.send(f"🔢 Next: **{st.get('expected_next', 1)}** | Goal: **{st.get('goal', 67)}**")
        await delete_command_msg()
    # The remainder requires a guild
    if not in_guild:
        return

    # ---------- ADMIN/MOD COMMANDS ----------
    if clower.startswith("!send "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        text = content.split(" ", 1)[1].strip()
        if not text:
            await message.channel.send("Usage: `!send <message>`"); return
@@ -1037,22 +1052,28 @@
        return

    if clower.startswith("!sendreact "):
        if not require_mod(): return
        rr_channel = guild.get_channel(REACTION_CHANNEL_ID)
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        rr_channel = message.guild.get_channel(REACTION_CHANNEL_ID)
        if not rr_channel:
            await message.channel.send("❗ REACTION_CHANNEL_ID is wrong or I can’t see that channel."); return
        body = content.split(" ", 1)[1].strip()
        sent = await rr_channel.send(body)
        for emoji in REACTION_ROLE_MAP.keys():
            try: await sent.add_reaction(emoji)
            except Exception: pass
        store = load_rr_store(); store["message_id"] = sent.id; store["channel_id"] = rr_channel.id; save_rr_store(store)
        store = load_rr_store()
        store["message_id"] = sent.id
        store["channel_id"] = rr_channel.id
        save_rr_store(store)
        await message.channel.send(f"✅ Reaction-roles set on message ID `{sent.id}` in {rr_channel.mention}.")
        await delete_command_msg()
        return

    # giveaways
    if clower.startswith("!gstart "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        try:
            _, rest = content.split(" ", 1)
            parts = [p.strip() for p in rest.split("|")]
@@ -1063,17 +1084,26 @@
        except Exception:
            await message.channel.send(
                "Usage: `!gstart <duration> | <winners> | <title> | <description>`\n"
                "Example: `!gstart 1h | 1 | 100 Robux | Join now!`"
                "Examples: `!gstart 1h | 1 | 100 Robux | Press Enter to join!`  or  `!gstart 0h 1m | 1 | Flash Drop | Hurry!`"
            ); return
        if not dur_s or dur_s <= 0 or winners_count < 1:
            await message.channel.send("❗ Bad duration or winners."); return
        ends_at = time() + dur_s
        emb = discord.Embed(title=title, description=desc, color=0x5865F2)
        emb.add_field(name="Duration", value=parts[0]); emb.add_field(name="Winners", value=str(winners_count))
        emb.add_field(name="Duration", value=parts[0])
        emb.add_field(name="Winners", value=str(winners_count))
        emb.set_footer(text="Press Enter to join • View Participants to see who’s in")
        sent = await message.channel.send(embed=emb, view=GiveawayView(0))
        mid = str(sent.id)
        GIVEAWAYS[mid] = {"channel_id": message.channel.id,"ends_at": ends_at,"winners": winners_count,"title": title,"desc": desc,"participants": [],"ended": False}
        GIVEAWAYS[mid] = {
            "channel_id": message.channel.id,
            "ends_at": ends_at,
            "winners": winners_count,
            "title": title,
            "desc": desc,
            "participants": [],
            "ended": False
        }
        save_giveaways(GIVEAWAYS)
        try: await sent.edit(view=GiveawayView(sent.id))
        except Exception: pass
@@ -1082,162 +1112,174 @@
        return

    if clower == "!gend":
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        active = [(int(mid), gw) for mid, gw in GIVEAWAYS.items() if not gw.get("ended")]
        if not active: await message.channel.send("No active giveaways."); return
        if not active:
            await message.channel.send("No active giveaways."); return
        latest_id = max(active, key=lambda t: t[0])[0]
        await end_giveaway(latest_id)
        await message.channel.send("✅ Giveaway ended.")
        await delete_command_msg()
        return

    if clower == "!greroll":
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        any_gw = [(int(mid), gw) for mid, gw in GIVEAWAYS.items()]
        if not any_gw: await message.channel.send("No giveaways found."); return
        if not any_gw:
            await message.channel.send("No giveaways found."); return
        latest_id = max(any_gw, key=lambda t: t[0])[0]
        gw = GIVEAWAYS.get(str(latest_id))
        if not gw: await message.channel.send("Not found."); return
        gw["ended"] = False; save_giveaways(GIVEAWAYS)
        if not gw:
            await message.channel.send("Not found."); return
        gw["ended"] = False
        save_giveaways(GIVEAWAYS)
        await end_giveaway(latest_id)
        await message.channel.send("✅ Rerolled.")
        await delete_command_msg()
        return

    # counting admin
    if clower.startswith("!countgoal "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        try:
            new_goal = int(content.split(maxsplit=1)[1]); assert new_goal > 0
        except Exception:
            await message.channel.send("Usage: `!countgoal <positive integer>`"); return
        COUNT_STATE["goal"] = new_goal; save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Goal set to **{new_goal}**."); await delete_command_msg(); return
        COUNT_STATE["goal"] = new_goal
        save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Goal set to **{new_goal}**.")
        await delete_command_msg()
        return

    if clower.startswith("!countnext "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        try:
            new_next = int(content.split(maxsplit=1)[1]); assert new_next > 0
        except Exception:
            await message.channel.send("Usage: `!countnext <positive integer>`"); return
        COUNT_STATE["expected_next"] = new_next; save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Next expected number set to **{new_next}**."); await delete_command_msg(); return
        COUNT_STATE["expected_next"] = new_next
        save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Next expected number set to **{new_next}**.")
        await delete_command_msg()
        return

    if clower == "!countreset":
        if not require_mod(): return
        COUNT_STATE["expected_next"] = 1; save_count_state(COUNT_STATE)
        await message.channel.send("✅ Counter reset. Next expected number is **1**."); await delete_command_msg(); return

    if clower.startswith("!doublecash"):
        if not require_mod(): return
        arg = clower.split(maxsplit=1)[1].strip() if " " in clower else ""
        if arg in ("on","off"):
            global DOUBLE_CASH
            DOUBLE_CASH = (arg == "on")
            await message.channel.send(f"💥 Double-cash **{arg.upper()}**.")
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        await message.channel.send("Usage: `!doublecash on` or `!doublecash off`"); return
        COUNT_STATE["expected_next"] = 1
        save_count_state(COUNT_STATE)
        await message.channel.send("✅ Counter reset. Next expected number is **1**.")
        await delete_command_msg()
        return

    # economy admin
    if clower.startswith("!addcash") or clower.startswith("!add "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        if not message.mentions:
            await message.channel.send("Usage: `!addcash @user <amount> [reason]`"); return
        target = message.mentions[0]
        tail = content.split(maxsplit=1)[1] if " " in content else ""
        tail = tail.replace(str(target.mention), "").strip()
        parts = tail.split(maxsplit=1)
        try: amount = int(parts[0])
        except Exception: await message.channel.send("Usage: `!addcash @user <amount> [reason]`"); return
        try:
            amount = int(parts[0])
        except Exception:
            await message.channel.send("Usage: `!addcash @user <amount> [reason]`"); return
        reason = parts[1] if len(parts) > 1 else "Adjustment"
        new_bal = await add_cash(target.id, amount)
        await message.channel.send(f"➕ Added **{amount}** cash to {target.mention}. Reason: {reason} (bal: {new_bal})")
        await delete_command_msg(); return
        await delete_command_msg()
        return

    if clower.startswith("!removecash") or clower.startswith("!remove "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        if not message.mentions:
            await message.channel.send("Usage: `!removecash @user <amount> [reason]`"); return
        target = message.mentions[0]
        tail = content.split(maxsplit=1)[1] if " " in content else ""
        tail = tail.replace(str(target.mention), "").strip()
        parts = tail.split(maxsplit=1)
        try: amount = int(parts[0])
        except Exception: await message.channel.send("Usage: `!removecash @user <amount> [reason]`"); return
        try:
            amount = int(parts[0])
        except Exception:
            await message.channel.send("Usage: `!removecash @user <amount> [reason]`"); return
        reason = parts[1] if len(parts) > 1 else "Adjustment"
        new_bal = await deduct_cash(target.id, amount)
        await message.channel.send(f"➖ Removed **{amount}** cash from {target.mention}. Reason: {reason} (bal: {new_bal})")
        await delete_command_msg(); return
        await delete_command_msg()
        return

    if clower == "!cashdrop":
        if not require_mod(): return
        ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
        if not ch:
            await message.channel.send("Cash drop channel not found."); return
    # manual cash drop (mod only)
    if clower.startswith("!cash drop"):
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        parts = content.split()
        amount = DROP_AMOUNT
        if len(parts) >= 3:
            try:
                amount = max(1, int(parts[2]))
            except Exception:
                pass
        phrase = four_words()
        embed = discord.Embed(title="[Cash] Cash drop!",
                              description=f"Type `!cash {phrase}` to collect **{DROP_AMOUNT}** cash!",
                              color=0x2ECC71)
        msg = await ch.send(embed=embed)
        embed = discord.Embed(
            title="[Cash] Cash drop!",
            description=f"Type `!cash {phrase}` to collect **{amount}** cash!",
            color=0x2ECC71
        )
        msg = await message.channel.send(embed=embed)
        try:
            await db_execute("""
                INSERT INTO muta_drops(channel_id, message_id, phrase, amount, created_at)
                VALUES($1,$2,$3,$4,NOW())
            """, CASH_DROP_CHANNEL_ID, msg.id, phrase.lower(), DROP_AMOUNT)
            await message.channel.send("✅ Drop created.")
        except Exception as e:
            await message.channel.send(f"Failed to record drop: {e}")
                VALUES($1,$2,$3,$4, NOW())
            """, message.channel.id, msg.id, phrase.lower(), amount)
        except Exception:
            try: await msg.delete()
            except Exception: pass
        await delete_command_msg(); return
        await delete_command_msg()
        return

    # level force-promote (mod only)
    if clower.startswith("!levelup "):
        if not require_mod(): return
        if not is_mod_or_admin(message.author):
            await delete_command_msg(); return
        if not message.mentions:
            await message.channel.send("Usage: `!levelup @user <rookie|squad|specialist|operative|legend>`")
            return
            await message.channel.send("Usage: `!levelup @user <Rookie|Squad|Specialist|Operative|Legend>`"); return
        target = message.mentions[0]
        role_key = clower.split()[-1]
        role_map = {
        tail = content.split(maxsplit=1)[1].replace(str(target.mention), "").strip().lower()
        name_map = {
            "rookie": ROLE_ROOKIE,
            "squad": ROLE_SQUAD,
            "squadmember": ROLE_SQUAD,
            "squad": ROLE_SQUAD, "squad member": ROLE_SQUAD,
            "specialist": ROLE_SPECIALIST,
            "operative": ROLE_OPERATIVE,
            "legend": ROLE_LEGEND,
        }
        rid = role_map.get(role_key)
        if not rid:
            await message.channel.send("Unknown level. Use one of: rookie, squad, specialist, operative, legend.")
            return
        role = guild.get_role(rid)
        role_id = name_map.get(tail)
        if not role_id:
            await message.channel.send("Role must be one of: Rookie, Squad, Specialist, Operative, Legend"); return
        role = message.guild.get_role(role_id)
        if not role:
            await message.channel.send("Role not found on this server.")
            return
            await message.channel.send("Configured role not found."); return
        try:
            await target.add_roles(role, reason="Manual level promotion (mod command)")
            ch = guild.get_channel(LEVEL_UP_CHANNEL_ID)
            if ch:
                await ch.send(f"{target.mention} reached the **{role.name}** role!")
            await message.channel.send("✅ Promoted.")
        except Exception as e:
            await message.channel.send(f"Failed: {e}")
        await delete_command_msg()
        return

    if clower == "!delete":
        if not require_mod(): return
        # delete bot’s last message in this channel
        async for m in message.channel.history(limit=50):
            if m.author.id == (bot.user.id if bot.user else 0):
                await try_delete(m)
                break
            await target.add_roles(role, reason="Manual level up")
        except Exception:
            pass
        ch = message.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send(f"{target.mention} reached the **{role.name}** role! 🎉")
        await delete_command_msg()
        return

    # ---------- EVERYONE ----------
    # ---------- EVERYONE COMMANDS ----------
    if clower in ("!balance", "!bal", "!cashme", "!mycash"):
        await ensure_user(message.author.id)
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", message.author.id)
        await message.channel.send(f"💰 {message.author.mention} balance: **{row['cash']}** cash")
        await message.channel.send(f"💰 {message.author.mention} your balance: **{row['cash']}** cash")
        await delete_command_msg()
        return

@@ -1251,12 +1293,11 @@
        await delete_command_msg()
        return

    # bug report
    if clower.startswith("!bugreport "):
        desc = content.split(" ", 1)[1].strip()
        if len(desc) < 5:
            await message.channel.send("Please include a short description."); return
        channel = guild.get_channel(BUGS_REVIEW_CHANNEL_ID)
        channel = message.guild.get_channel(BUGS_REVIEW_CHANNEL_ID)
        if not channel:
            await message.channel.send("Bug review channel not found."); return
        view = BugApproveView(message.author.id, desc)
@@ -1265,7 +1306,7 @@
        await delete_command_msg()
        return

    # claim cash drop: !cash <four words>
    # Claim a cash drop
    if clower.startswith("!cash"):
        parts = content.split()
        if len(parts) >= (1 + DROP_WORD_COUNT):
@@ -1292,8 +1333,8 @@
            await message.channel.send(f"Usage: `!cash <{DROP_WORD_COUNT} words from the embed>`")
            return

    # ---------- NON-COMMAND ENFORCERS ----------
    # Counting channel enforcement
    # ---------- NON-COMMANDS ----------
    # Counting enforcement
    if message.channel.id == COUNT_CHANNEL_ID and not message.author.bot:
        if content.startswith("!"):
            return
@@ -1307,7 +1348,7 @@
        save_count_state(COUNT_STATE)
        return

    # W/F/L reactions
    # W/F/L auto reactions
    if message.channel.id == WFL_CHANNEL_ID:
        t = clower
        has_wfl = (
@@ -1325,49 +1366,48 @@
            except Exception as e:
                print(f"[wfl] failed to add reactions: {e}")

    # Earn cash + activity for messages (non-commands)
    # Earn cash + activity
    if message.channel.id in EARN_CHANNEL_IDS and not content.startswith("!"):
        now = datetime.now(tz=TZ)
        try:
            await earn_for_message(message.author.id, now, len(content), guild, message.author.id)
            await earn_for_message(message.author.id, now, len(content), message.guild, message.author.id)
        except Exception as e:
            print(f"[earn] error: {e}")

    # Cross-trade detector (skip excluded categories and mod-log)
    if message.channel.id != MOD_LOG_CHANNEL_ID:
        cat_id = message.channel.category_id if message.channel and hasattr(message.channel, "category_id") else None
        if cat_id not in CROSSTRADE_EXCLUDED_CATEGORY_IDS:
            raw = content
            if raw.strip():
                norm = normalize_text(raw)
                hits = set()
                for w in BUY_SELL_WORDS:
                    if f" {w} " in f" {norm} ": hits.add(w)
                for w in CROSSTRADE_HINTS:
                    if f" {w} " in f" {norm} ": hits.add(w)
                for rx in CROSSTRADE_PATTERNS:
                    if rx.search(raw) or rx.search(norm): hits.add(rx.pattern)
                if hits:
                    nowt = time()
                    user_key = f"report_cool:{message.author.id}"
                    last_s = await db_get_meta(user_key)
                    last = float(last_s) if last_s else 0.0
                    if nowt - last >= 120:  # throttle per-user
                        await db_set_meta(user_key, str(nowt))
                        modlog = guild.get_channel(MOD_LOG_CHANNEL_ID)
                        if modlog:
                            embed = discord.Embed(
                                title="⚠️ Possible Cross-Trading / Black-Market Activity",
                                description=(f"**User:** {message.author.mention} (`{message.author}`)\n"
                                             f"**Channel:** {message.channel.mention}\n"
                                             f"**Message:**\n{message.content[:1000]}"),
                                color=0xE67E22
                            )
                            embed.add_field(name="Triggers", value=", ".join(sorted(hits))[:1024], inline=False)
                            embed.add_field(name="Jump", value=f"[Go to message]({message.jump_url})", inline=False)
                            embed.timestamp = discord.utils.utcnow()
                            embed.set_footer(text=f"User ID: {message.author.id}")
                            await modlog.send(embed=embed)
    # Cross-trade detector (skip excluded categories & mod-log only)
    cat_id = message.channel.category_id if message.channel and getattr(message.channel, "category_id", None) else None
    if message.channel.id != MOD_LOG_CHANNEL_ID and (cat_id not in CROSS_TRADE_EXCLUDED_CATEGORY_IDS):
        raw = content
        if raw.strip():
            norm = normalize_text(raw)
            hits = set()
            for w in BUY_SELL_WORDS:
                if f" {w} " in f" {norm} ": hits.add(w)
            for w in CROSSTRADE_HINTS:
                if f" {w} " in f" {norm} ": hits.add(w)
            for rx in CROSSTRADE_PATTERNS:
                if rx.search(raw) or rx.search(norm): hits.add(rx.pattern)
            if hits:
                nowt = time()
                user_key = f"report_cool:{message.author.id}"
                last_s = await db_get_meta(user_key)
                last = float(last_s) if last_s else 0.0
                if nowt - last >= 120:  # 2 min throttle/user
                    await db_set_meta(user_key, str(nowt))
                    modlog = message.guild.get_channel(MOD_LOG_CHANNEL_ID)
                    if modlog:
                        embed = discord.Embed(
                            title="⚠️ Possible Cross-Trading / Black-Market Activity",
                            description=(f"**User:** {message.author.mention} (`{message.author}`)\n"
                                         f"**Channel:** {message.channel.mention}\n"
                                         f"**Message:**\n{message.content[:1000]}"),
                            color=0xE67E22
                        )
                        embed.add_field(name="Triggers", value=", ".join(sorted(hits))[:1024], inline=False)
                        embed.add_field(name="Jump", value=f"[Go to message]({message.jump_url})", inline=False)
                        embed.timestamp = discord.utils.utcnow()
                        embed.set_footer(text=f"User ID: {message.author.id}")
                        await modlog.send(embed=embed)

# ================== MEMBER JOIN ==================
@bot.event
@@ -1406,6 +1446,7 @@
                await modlog.send(embed=em)
            return

    # assign newcomer
    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    if newcomer:
        try:
@@ -1417,37 +1458,14 @@
    if ch:
        embed = discord.Embed(
            title=f"Welcome to {guild.name}, {member.name}!",
            description=(f"Hey {member.mention}! Welcome to the **Mutapapa Official Discord Server!** "
                         "We hope you have a great time here!"),
            description=(f"Hey {member.mention}! Welcome to the **Mutapapa Official Discord Server!**"),
            color=0x0089FF
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if BANNER_URL and "PUT_A_PUBLIC_IMAGE_URL_HERE" not in BANNER_URL:
        if BANNER_URL:
            embed.set_image(url=BANNER_URL)
        await ch.send(embed=embed)

# Auto-promote newcomer to member after 3 days
@tasks.loop(hours=6)
async def newcomer_promote_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    member_role = guild.get_role(MEMBER_ROLE_ID)
    if not newcomer or not member_role:
        return
    now = datetime.now(tz=TZ)
    for m in newcomer.members:
        joined = m.joined_at.astimezone(TZ) if m.joined_at else None
        if joined and (now - joined) >= timedelta(days=3):
            try:
                await m.remove_roles(newcomer, reason="3 days passed")
                await m.add_roles(member_role, reason="3 days passed — auto promote")
            except Exception:
                pass

newcomer_promote_loop.start()

# ================== REACTION ROLES ==================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
@@ -1462,12 +1480,9 @@
    role_id = REACTION_ROLE_MAP.get(emoji)
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    role = guild.get_role(role_id)
    if not role: return
    member = guild.get_member(payload.user_id)
    if not member: return
    guild = bot.get_guild(payload.guild_id);  role = guild.get_role(role_id) if guild else None
    member = guild.get_member(payload.user_id) if guild else None
    if not (guild and role and member): return
    try:
        if role not in member.roles:
            await member.add_roles(role, reason="Reaction role add")
@@ -1485,12 +1500,9 @@
    role_id = REACTION_ROLE_MAP.get(emoji)
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    role = guild.get_role(role_id)
    if not role: return
    member = guild.get_member(payload.user_id)
    if not member: return
    guild = bot.get_guild(payload.guild_id);  role = guild.get_role(role_id) if guild else None
    member = guild.get_member(payload.user_id) if guild else None
    if not (guild and role and member): return
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Reaction role remove")
@@ -1505,30 +1517,4 @@
    bot.run(token)

if __name__ == "__main__":
    main()

# --- keep your loop definitions above ---
# e.g.:
# @tasks.loop(minutes=5)
# async def newcomer_promote_loop(): ...
# @tasks.loop(seconds=45)
# async def drops_loop(): ...
# @tasks.loop(minutes=2)
# async def x_posts_loop(): ...
# @tasks.loop(minutes=3)
# async def yt_poll_loop(): ...
# @tasks.loop(minutes=1)
# async def monthly_reset_loop(): ...

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")

    # init services that need the loop
    await db_init()
    await start_webserver()

    # start background loops once
    for loop_obj in (yt_poll_loop, x_posts_loop, drops_loop, monthly_reset_loop, newcomer_promote_loop):
        if not loop_obj.is_running():
            loop_obj.start()
    main()