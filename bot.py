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

from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
# ================== CORE CONFIG ==================
GUILD_ID = 1411205177880608831

WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID   = 1411957261009555536
MEMBER_ROLE_ID     = 1411938410041708585

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

# Counting
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
YT_PING_ROLE_ID        = 1412989373556850829
YT_CALLBACK_PATH       = "/yt"
YT_HUB                 = "https://pubsubhubbub.appspot.com"
YT_SECRET              = "mutapapa-youtube"
YT_CACHE_FILE          = "yt_last_video.json"

# X / Twitter via Nitter/Bridge
X_USERNAME = "Real_Mutapapa"
X_PING_ROLE_ID = 1414001344297172992
X_RSS_FALLBACKS = [
    f"https://nitter.net/{X_USERNAME}/rss",
    f"https://nitter.mailt.buzz/{X_USERNAME}/rss",
    f"https://nitter.poast.org/{X_USERNAME}/rss",
]
X_RSS_URL = os.getenv("X_RSS_URL") or X_RSS_FALLBACKS[0]
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_CACHE_FILE = "x_last_item.json"

# Banner image (set BANNER_URL in environment)
BANNER_URL = os.getenv("BANNER_URL", "").strip()

# Bug review + penalty approvals
BUGS_REVIEW_CHANNEL_ID = 1414124214956593242
PENALTY_CHANNEL_ID     = 1414124795418640535  # rule-break penalty confirm buttons

# Cash drop announcements
CASH_DROP_CHANNEL_ID = 1414120740327788594

# Helpful channels
CASH_ANNOUNCE_CHANNEL_ID = 1414124134903844936
LEADERBOARD_CHANNEL_ID   = 1414124214956593242

# Edmonton time
TZ = ZoneInfo("America/Edmonton")

# ================== ECONOMY CONFIG ==================
DAILY_CAP = 1200
DOUBLE_CASH = False

def cash_per_message(msg_len: int) -> int:
    if msg_len <= 10: return 10
    if msg_len <= 25: return 20
    if msg_len <= 50: return 35
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
ROLE_OPERATIVE   = 1414819574595752037
ROLE_LEGEND      = 1414819873644455956

ACTIVITY_THRESHOLDS = [
    (ROLE_ROOKIE,     2000),
    (ROLE_SQUAD,     10000),
    (ROLE_SPECIALIST, 50000),
    (ROLE_OPERATIVE, 100000),
    (ROLE_LEGEND,   400000),
]

# Mod roles
HELP_MOD_ROLE_IDS = {1413663966349234320, 1411940485005578322, 1413991410901713088}

# ================== FILE HELPERS ==================
CONFIG_FILE     = "config.json"
GIVEAWAYS_FILE  = "giveaways.json"
COUNT_STATE     = {}
GIVEAWAYS       = {}

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, d):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

def load_config():
    return load_json(CONFIG_FILE, {"age_gate_enabled": True, "min_account_age_sec": 7 * 24 * 3600})

def save_config(cfg): save_json(CONFIG_FILE, cfg)
def load_rr_store(): return load_json(RR_STORE_FILE, {})
def save_rr_store(d): save_json(RR_STORE_FILE, d)
def load_x_cache(): return load_json(X_CACHE_FILE, {})
def save_x_cache(d): save_json(X_CACHE_FILE, d)
def load_yt_cache(): return load_json(YT_CACHE_FILE, {})
def save_yt_cache(d): save_json(YT_CACHE_FILE, d)

def load_count_state():
    d = load_json(COUNT_STATE_FILE, {"expected_next": 1, "goal": 67})
    d.setdefault("expected_next", 1)
    d.setdefault("goal", 67)
    return d

def save_count_state(d): save_json(COUNT_STATE_FILE, d)

def load_giveaways():
    data = load_json(GIVEAWAYS_FILE, {})
    return data if isinstance(data, dict) else {}

def save_giveaways(d): save_json(GIVEAWAYS_FILE, d)

CONFIG      = load_config()
COUNT_STATE = load_count_state()
GIVEAWAYS   = load_giveaways()

# ================== DATABASE ==================
DB_URL = os.getenv("DATABASE_URL")

async def db_init():
    global _pool
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)

    async with _pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_users (
            user_id BIGINT PRIMARY KEY,
            cash BIGINT NOT NULL DEFAULT 0,
            last_earn_ts TIMESTAMPTZ,
            today_earned BIGINT NOT NULL DEFAULT 0,
            bug_rewards_this_month INTEGER NOT NULL DEFAULT 0,
            activity_points BIGINT NOT NULL DEFAULT 0
        );
        """)

        await con.execute("ALTER TABLE muta_users ADD COLUMN IF NOT EXISTS activity_points BIGINT NOT NULL DEFAULT 0;")
        await con.execute("ALTER TABLE muta_users ADD COLUMN IF NOT EXISTS today_earned BIGINT NOT NULL DEFAULT 0;")

        await con.execute("""
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

        await con.execute("CREATE INDEX IF NOT EXISTS idx_muta_drops_created_at ON muta_drops (created_at);")
# ================== DB HELPERS ==================
async def db_fetchrow(query, *args):
    async with _pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def db_fetch(query, *args):
    async with _pool.acquire() as con:
        return await con.fetch(query, *args)

async def db_execute(query, *args):
    async with _pool.acquire() as con:
        return await con.execute(query, *args)

async def db_get_meta(key: str):
    row = await db_fetchrow("SELECT value FROM muta_meta WHERE key=$1", key)
    return row["value"] if row else None

async def db_set_meta(key: str, val: str):
    await db_execute("""
    INSERT INTO muta_meta(key, value)
    VALUES($1,$2)
    ON CONFLICT (key) DO UPDATE SET value=excluded.value
    """, key, val)

# ================== CASH HELPERS ==================
async def ensure_user(uid: int):
    await db_execute("INSERT INTO muta_users(user_id) VALUES($1) ON CONFLICT DO NOTHING", uid)

async def add_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("UPDATE muta_users SET cash=cash+$1 WHERE user_id=$2 RETURNING cash", amount, uid)
    return int(row["cash"]) if row else 0

async def deduct_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("UPDATE muta_users SET cash=GREATEST(0,cash-$1) WHERE user_id=$2 RETURNING cash", amount, uid)
    return int(row["cash"]) if row else 0

async def leaderboard_top(n: int = 10):
    return await db_fetch("SELECT user_id, cash FROM muta_users ORDER BY cash DESC LIMIT $1", n)

# ================== VIEWS ==================
class BugApproveView(View):
    def __init__(self, uid: int, desc: str):
        super().__init__(timeout=None)
        self.uid = uid
        self.desc = desc

    @button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction, _):
        await add_cash(self.uid, BUG_REWARD_AMOUNT)
        await db_execute("UPDATE muta_users SET bug_rewards_this_month=bug_rewards_this_month+1 WHERE user_id=$1", self.uid)
        await interaction.response.edit_message(content=f"✅ Bug approved. +{BUG_REWARD_AMOUNT} cash to <@{self.uid}>", view=None)
        try:
            u = await bot.fetch_user(self.uid)
            await u.send(f"✅ Your bug report was approved: `{self.desc}` (+{BUG_REWARD_AMOUNT} cash)")
        except: pass

    @button(label="Reject", style=discord.ButtonStyle.red)
    async def reject(self, interaction, _):
        await interaction.response.edit_message(content="❌ Bug rejected.", view=None)

# ================== HELP EMBED ==================
def is_mod_or_admin(member: discord.Member | None) -> bool:
    if not member: return False
    if member.guild_permissions.administrator: return True
    return any(r.id in HELP_MOD_ROLE_IDS for r in member.roles)

def build_commands_embed(author: discord.Member) -> discord.Embed:
    embed = discord.Embed(title="📜 Mutapapa Bot Commands", color=0x5865F2)
    everyone = [
        ("!balance | !bal | !cashme | !mycash", "Check your balance."),
        ("!leaderboard", "Top 10 richest."),
        (f"!cash <{DROP_WORD_COUNT} words>", "Claim a drop."),
        ("!bugreport <desc>", f"Report bug (+{BUG_REWARD_AMOUNT} if approved)."),
        ("!countstatus", "See current count goal & next number."),
        ("!ping", "Health check."),
    ]
    embed.add_field(name="👥 Everyone", value="\n".join([f"**{a}** — {b}" for a,b in everyone]), inline=False)
    if is_mod_or_admin(author):
        mods = [
            ("!send <msg>", "Bot says message."),
            ("!sendreact <msg>", "RR message w/ emojis."),
            ("!gstart <dur>|<winners>|<title>|<desc>", "Start giveaway."),
            ("!gend / !greroll", "End or reroll giveaway."),
            ("!countgoal <n> / !countnext <n> / !countreset", "Control counting."),
            ("!addcash / !removecash", "Adjust balances."),
            ("!cash drop [amt]", "Manual drop."),
            ("!levelup @user <role>", "Force promote."),
            ("!doublecash on/off", "Toggle double cash."),
        ]
        embed.add_field(name="🛠️ Mods", value="\n".join([f"**{a}** — {b}" for a,b in mods]), inline=False)
    return embed

# ================== MESSAGE HANDLING ==================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    content = message.content.strip()
    clower  = content.lower()
    in_guild = message.guild is not None

    async def delete_cmd():
        try: await message.delete()
        except: pass

    # help
    if clower in ("!help","!commands"):
        await message.channel.send(embed=build_commands_embed(message.author))
        if in_guild: await delete_cmd()
        return

    # ping
    if clower == "!ping":
        await message.channel.send("pong 🏓")
        if in_guild: await delete_cmd()
        return

    # balance
    if clower in ("!balance","!bal","!cashme","!mycash"):
        await ensure_user(message.author.id)
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", message.author.id)
        await message.channel.send(f"💰 {message.author.mention} balance: **{row['cash']}** cash")
        if in_guild: await delete_cmd()
        return

    # leaderboard
    if clower == "!leaderboard":
        rows = await leaderboard_top()
        desc = "\n".join([f"**{i+1}.** <@{r['user_id']}> — {r['cash']} cash" for i,r in enumerate(rows)])
        await message.channel.send(embed=discord.Embed(title="🏆 Leaderboard", description=desc, color=0xFFD700))
        return

    # bugreport
    if clower.startswith("!bugreport "):
        desc = content.split(" ",1)[1].strip()
        if len(desc)<5: 
            await message.channel.send("❗ Description too short."); return
        ch = message.guild.get_channel(BUGS_REVIEW_CHANNEL_ID)
        if ch: await ch.send(f"🐞 Bug report from {message.author.mention}:\n`{desc}`", view=BugApproveView(message.author.id, desc))
        if in_guild: await delete_cmd()
        return

    # cash claim
    if clower.startswith("!cash "):
        phrase = " ".join(content.split()[1:]).lower()
        row = await db_fetchrow("SELECT * FROM muta_drops WHERE phrase=$1 AND claimed_by IS NULL", phrase)
        if not row: 
            await message.channel.send("❌ Invalid or already claimed."); return
        await db_execute("UPDATE muta_drops SET claimed_by=$1, claimed_at=NOW() WHERE id=$2", message.author.id, row["id"])
        await add_cash(message.author.id, row["amount"])
        await message.channel.send(f"✅ {message.author.mention} claimed {row['amount']} cash!")
        return

    # counting enforcement
    if in_guild and message.channel.id == COUNT_CHANNEL_ID:
        if not content.isdigit():
            await delete_cmd(); return
        num = int(content)
        if num != COUNT_STATE["expected_next"]:
            await delete_cmd(); return
        COUNT_STATE["expected_next"] += 1
        save_count_state(COUNT_STATE)

    # cross-trade detection
    if in_guild and message.channel.id != MOD_LOG_CHANNEL_ID:
        cat = getattr(message.channel, "category_id", None)
        if cat not in CROSS_TRADE_EXCLUDED_CATEGORY_IDS:
            text = content.lower()
            hits = []
            for w in ["trade","sell","buy","paypal","btc","robux","cross trade"]:
                if w in text: hits.append(w)
            if hits:
                ch = message.guild.get_channel(MOD_LOG_CHANNEL_ID)
                if ch:
                    embed = discord.Embed(title="⚠️ Possible Cross-Trade", description=message.content, color=0xE67E22)
                    embed.add_field(name="User", value=message.author.mention)
                    embed.add_field(name="Hits", value=", ".join(hits))
                    await ch.send(embed=embed)

# ================== REACTION ROLES ==================
@bot.event
async def on_raw_reaction_add(p: discord.RawReactionActionEvent):
    data = load_rr_store()
    if p.message_id != data.get("message_id"): return
    role_id = REACTION_ROLE_MAP.get(str(p.emoji))
    if not role_id: return
    g = bot.get_guild(p.guild_id); m = g.get_member(p.user_id) if g else None
    r = g.get_role(role_id) if g else None
    if g and m and r: await m.add_roles(r, reason="Reaction role add")

@bot.event
async def on_raw_reaction_remove(p: discord.RawReactionActionEvent):
    data = load_rr_store()
    if p.message_id != data.get("message_id"): return
    role_id = REACTION_ROLE_MAP.get(str(p.emoji))
    if not role_id: return
    g = bot.get_guild(p.guild_id); m = g.get_member(p.user_id) if g else None
    r = g.get_role(role_id) if g else None
    if g and m and r: await m.remove_roles(r, reason="Reaction role remove")

# ================== READY ==================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await db_init()
    if not drops_loop.is_running(): drops_loop.start()
    if not yt_poll_loop.is_running(): yt_poll_loop.start()
    if not x_posts_loop.is_running(): x_posts_loop.start()
    if not monthly_reset_loop.is_running(): monthly_reset_loop.start()
    if not newcomer_promote_loop.is_running(): newcomer_promote_loop.start()

# ================== RUN ==================
def main():
    token = os.getenv("BOT_TOKEN")
    bot.run(token)

if __name__ == "__main__":
    main()
