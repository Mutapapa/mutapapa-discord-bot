# bot.py
import os
import asyncio
import json
import re
import hmac
import hashlib
import xml.etree.ElementTree as ET
import random
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
GUILD_ID = 1411205177880608831

WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID   = 1411957261009555536
MEMBER_ROLE_ID     = 1411938410041708585

# Mod logs (rule detector / cross-trade alerts land here)
MOD_LOG_CHANNEL_ID = 1413297073348018299

# Monthly-reset announcements go to all of these:
SEASON_RESET_ANNOUNCE_CHANNEL_IDS = [
    1414000088790863874,
    1411931034026643476,
    1411930067994411139,
    1411930091109224479,
    1411930689460240395,
    1414120740327788594,
]

# Bug review (where !bugreport is posted with Approve/Reject buttons)
BUG_REVIEW_CHANNEL_ID = 1414124214956593242

# Penalty approvals (Yes/No buttons for cash deduction)
PENALTY_CHANNEL_ID = 1414124795418640535

# Reaction Roles
REACTION_CHANNEL_ID = 1414001588091093052
REACTION_ROLE_MAP = {
    "📺": 1412989373556850829,
    "🔔": 1412993171670958232,
    "✖️": 1414001344297172992,
    "🎉": 1412992931148595301,
}
RR_STORE_FILE = "reaction_msg.json"

# W/F/L vote channel (auto add 🇼 🇫 🇱)
WFL_CHANNEL_ID = 1411931034026643476

# Counting Channel (only numbers in order)
COUNT_CHANNEL_ID = 1414051875329802320
COUNT_STATE_FILE = "count_state.json"

# Channels to monitor for rule-breaking keywords (detector)
MONITORED_CHANNEL_IDS = [
    1411930067994411139, 1411930091109224479, 1411930638260502638,
    1411930689460240395, 1411931034026643476
]

# Who can see Admin/Mods commands in !help/!commands
COMMANDS_ADMIN_ROLE_IDS = {
    1413663966349234320,
    1411940485005578322,
    1413991410901713088,
}

# YouTube (WebSub push)
YT_CHANNEL_ID          = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID        = 1412989373556850829
YT_CALLBACK_PATH       = "/yt/webhook"
YT_HUB                 = "https://pubsubhubbub.appspot.com"
YT_SECRET              = "mutapapa-youtube"

# X / Twitter (RSS via Nitter/Bridge) — multiple fallbacks
X_USERNAME = "Real_Mutapapa"
X_RSS_FALLBACKS = [
    f"https://nitter.net/{X_USERNAME}/rss",
    f"https://nitter.mailt.buzz/{X_USERNAME}/rss",
    f"https://nitter.poast.org/{X_USERNAME}/rss",
]
X_RSS_URL = os.getenv("X_RSS_URL") or X_RSS_FALLBACKS[0]
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_CACHE_FILE = "x_last_item.json"

# Banner image
BANNER_URL = "https://cdn.discordapp.com/attachments/1411930091109224479/1413654925602459769/Welcome_to_the_Mutapapa_Official_Discord_Server_Image.png?ex=68bcb83e&is=68bb66be&hm=f248257c26608d0ee69b8baab82f62aea768f15f090ad318617e68350fe3b5ac&"

# Cash drop announcements channel
CASH_DROP_CHANNEL_ID = 1414120740327788594

# Optional: nice places to send bot announcements/leaderboard
CASH_ANNOUNCE_CHANNEL_ID   = 1414124134903844936
LEADERBOARD_CHANNEL_ID     = 1414124214956593242

# Age Gate defaults (persisted to config.json)
CONFIG_FILE = "config.json"

# Giveaways (persisted)
GIVEAWAYS_FILE = "giveaways.json"

# Level role mappings (persisted in DB)
# Use !setlevelrole and !listlevelroles to manage

# Edmonton time
TZ = ZoneInfo("America/Edmonton")

# ================== ECONOMY RULES ==================
# message earning
EARN_CHANNEL_IDS = [
    1411930638260502638,1411486271464935456,1413297073348018299,1411935203953217566,
    1411435784250331288,1412144563144888452,1411931216608755782,1414000975680897128,
    1411433941403177054,1411931171671117854,1411946767414591538,1413999346592256050,
    1414001588091093052
]
EARN_COOLDOWN_SEC = 180          # 3 minutes
EARN_PER_TICK     = 200          # base
DAILY_CAP         = 2000         # (base + tier bonus) per day; random drops excluded
DOUBLE_CASH       = False        # toggled by !doublecash on/off

# tiered message-length bonus per tick (included in daily cap)
def tier_bonus(msg_len: int) -> int:
    if msg_len <= 9: return 0
    if msg_len <= 49: return 50
    if msg_len <= 99: return 80
    return 100

# random drops (4 per local day)
DROPS_PER_DAY     = 4
DROP_AMOUNT       = 225
DROP_WORD_COUNT   = 4  # "!cash <word1> <word2> <word3> <word4>"

# bug reward
BUG_REWARD_AMOUNT = 350
BUG_REWARD_LIMIT_PER_MONTH = 2  # per user
BUGS_CHANNEL_ID = 0  # (unused placeholder, set if you create a dedicated submit channel)

# levels: +1 level per 3000 cash (cosmetic; you’ll map roles yourself later)
CASH_PER_LEVEL = 3000

# ================== RULE DETECTOR (keywords & patterns) ==================
BUY_SELL_WORDS = {
    "buy", "sell", "selling", "trading", "trade", "cross trade", "cross-trade",
    "paypal", "venmo", "cashapp", "btc", "crypto", "robux", "gift card", "giftcard",
    "real money", "rm", "usd", "nzd", "cad", "aud", "£", "$", "€"
}
CROSSTRADE_HINTS = {
    "dm me price", "dm for price", "willing to pay", "offer cash", "cash ready",
    "outside server", "dms open", "real life money", "irl money"
}
CROSSTRADE_PATTERNS = [
    re.compile(r"\b\d+\s*(usd|cad|aud|nzd|eur|gbp|\$|€|£)\b", re.I),
    re.compile(r"\b(paypal|venmo|cashapp|btc|crypto)\b", re.I),
    re.compile(r"\b(sell(ing)?|buy(ing)?|trade|trading)\b", re.I),
]

# detector runtime controls
_last_report_by_user: dict[int, float] = {}
_report_cooldown_sec = 90  # don’t spam modlog
def normalize_text(s: str) -> str:
    t = s.lower()
    t = re.sub(r"[_*`~>|]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return f" {t.strip()} "

# ================== LOW-LEVEL PERSIST HELPERS ==================
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def load_config():
    # rule_detector default ON
    return load_json(CONFIG_FILE, {
        "age_gate_enabled": True,
        "min_account_age_sec": 7 * 24 * 3600,
        "rule_detector_enabled": True
    })

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def load_rr_store():
    return load_json(RR_STORE_FILE, {})

def save_rr_store(d):
    save_json(RR_STORE_FILE, d)

def load_x_cache():
    return load_json(X_CACHE_FILE, {})

def save_x_cache(d):
    save_json(X_CACHE_FILE, d)

def load_count_state():
    d = load_json(COUNT_STATE_FILE, {"expected_next": 1, "goal": 67})
    d.setdefault("expected_next", 1)
    d.setdefault("goal", 67)
    return d

def save_count_state(d):
    save_json(COUNT_STATE_FILE, d)

def load_giveaways():
    data = load_json(GIVEAWAYS_FILE, {})
    return data if isinstance(data, dict) else {}

def save_giveaways(d):
    save_giveaways_lock = d  # silence linter; nothing fancy
    save_json(GIVEAWAYS_FILE, d)

CONFIG      = load_config()
COUNT_STATE = load_count_state()
GIVEAWAYS   = load_giveaways()

# ================== DISCORD CLIENT ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# ================== DB (Supabase Postgres via asyncpg) ==================
DB_URL = os.getenv("SUPABASE_DB_URL", "").strip()
if not DB_URL:
    raise RuntimeError("SUPABASE_DB_URL is missing. Provide a postgresql:// DSN (not the https REST URL).")

scheme = urlparse(DB_URL).scheme.lower()
if scheme not in ("postgresql", "postgres"):
    raise RuntimeError(
        f"SUPABASE_DB_URL must start with postgresql:// or postgres://, got '{scheme}'. "
        "Use the Transaction Pooler DSN from Supabase, e.g. "
        "postgresql://USER:PASSWORD@...pooler.supabase.com:6543/postgres?sslmode=require"
    )

_pool: asyncpg.Pool | None = None

async def db_init():
    """Create pool and ensure tables exist."""
    global _pool
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)

    async with _pool.acquire() as con:
        # users table
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_users (
            user_id BIGINT PRIMARY KEY,
            cash BIGINT NOT NULL DEFAULT 0,
            last_earn_ts TIMESTAMPTZ,
            today_earned BIGINT NOT NULL DEFAULT 0,
            bug_rewards_this_month INTEGER NOT NULL DEFAULT 0
        );
        """)

        # drops table
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

        # meta kv
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # level → role mapping
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_level_roles (
            level INTEGER PRIMARY KEY,
            role_id BIGINT NOT NULL
        );
        """)

        # helpful index
        await con.execute("""
        CREATE INDEX IF NOT EXISTS idx_muta_drops_created_at ON muta_drops (created_at);
        """)

async def db_fetchrow(query, *args):
    async with _pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def db_execute(query, *args):
    async with _pool.acquire() as con:
        return await con.execute(query, *args)

async def db_fetch(query, *args):
    async with _pool.acquire() as con:
        return await con.fetch(query, *args)

# ================== AIOHTTP (YouTube webhook) ==================
app = web.Application()

async def yt_webhook_handler(request: web.Request):
    if request.method == "GET":
        return web.Response(text=request.query.get("hub.challenge") or "ok")

    body = await request.read()

    if YT_SECRET:
        sig = request.headers.get("X-Hub-Signature", "")
        try:
            alg, hexdigest = sig.split("=", 1)
            digestmod = {"sha1": hashlib.sha1, "sha256": hashlib.sha256}.get(alg.lower())
            if digestmod:
                mac = hmac.new(YT_SECRET.encode(), body, digestmod)
                if not hmac.compare_digest(mac.hexdigest(), hexdigest):
                    return web.Response(status=400, text="bad signature")
        except Exception:
            return web.Response(status=400, text="bad signature")

    try:
        root = ET.fromstring(body.decode("utf-8", errors="ignore"))
        ns = {"atom":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return web.Response(text="no entry")
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
                embed = discord.Embed(
                    title=title or "New upload!",
                    url=f"https://youtu.be/{vid}",
                    description="A new video just dropped 🔔",
                    color=0xE62117
                )
                embed.set_image(url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
                allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
                await ch.send(content=role.mention, embed=embed, allowed_mentions=allowed)
                print(f"[yt-webhook] announced {vid}")

    return web.Response(text="ok")

async def health(_):
    return web.Response(text="ok")

app.add_routes([
    web.get(YT_CALLBACK_PATH, yt_webhook_handler),
    web.post(YT_CALLBACK_PATH, yt_webhook_handler),
    web.get("/health", health),
])

runner = web.AppRunner(app)

async def start_webserver():
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[yt-webhook] listening on 0.0.0.0:{port}{YT_CALLBACK_PATH}")

async def websub_subscribe(public_base_url: str):
    topic = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"
    callback = f"{public_base_url.rstrip('/')}{YT_CALLBACK_PATH}"
    data = {"hub.mode":"subscribe","hub.topic":topic,"hub.callback":callback,"hub.verify":"async"}
    if YT_SECRET:
        data["hub.secret"] = YT_SECRET
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{YT_HUB}/subscribe", data=data, timeout=10) as resp:
                print(f"[yt-webhook] subscribe {resp.status} -> {callback}")
    except Exception as e:
        print(f"[yt-webhook] subscribe error: {e}")

# ================== GIVEAWAYS ==================
class GiveawayView(View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        self._entered: set[int] = set()  # in-memory anti-double-click

    @button(label="Enter", style=discord.ButtonStyle.primary, emoji="🎉", custom_id="gw_enter")
    async def enter_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        mid = str(self.message_id)
        gw = GIVEAWAYS.get(mid)
        if not gw or gw.get("ended"):
            return await interaction.response.send_message("This giveaway is closed.", ephemeral=True)
        if interaction.user.id in self._entered:
            return await interaction.response.send_message("You’re already in 🎉", ephemeral=True)

        parts = set(gw.get("participants", []))
        if interaction.user.id in parts:
            self._entered.add(interaction.user.id)
            return await interaction.response.send_message("You’re already in 🎉", ephemeral=True)

        parts.add(interaction.user.id)
        gw["participants"] = list(parts)
        GIVEAWAYS[mid] = gw
        save_giveaways(GIVEAWAYS)
        self._entered.add(interaction.user.id)
        await interaction.response.send_message("Entered! 🎉", ephemeral=True)

    @button(label="View Participants", style=discord.ButtonStyle.secondary, emoji="👀", custom_id="gw_view")
    async def view_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        mid = str(self.message_id)
        gw = GIVEAWAYS.get(mid)
        if not gw:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)
        parts = gw.get("participants", [])
        if not parts:
            return await interaction.response.send_message("No participants yet.", ephemeral=True)
        mentions = [f"<@{uid}>" for uid in parts][:100]
        await interaction.response.send_message(f"Participants ({len(parts)}):\n" + ", ".join(mentions), ephemeral=True)

async def schedule_giveaway_end(message_id: int, ends_at_unix: float):
    await asyncio.sleep(max(0, ends_at_unix - time()))
    await end_giveaway(message_id)

async def end_giveaway(message_id: int):
    mid = str(message_id)
    gw = GIVEAWAYS.get(mid)
    if not gw or gw.get("ended"):
        return

    channel = bot.get_channel(gw["channel_id"])
    if not channel:
        gw["ended"] = True
        save_giveaways(GIVEAWAYS)
        return
    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        msg = None

    parts = [p for p in set(gw.get("participants", [])) if isinstance(p, int)]
    winners_count = max(1, int(gw.get("winners", 1)))
    winners = random.sample(parts, k=min(winners_count, len(parts))) if parts else []

    title = gw.get("title") or "Giveaway"
    desc  = gw.get("desc") or ""
    win_text = ("None" if not winners else " ".join(f"<@{w}>" for w in winners))

    embed = discord.Embed(
        title=f"🎉 {title} — ENDED",
        description=f"{desc}\n\n**Winners:** {win_text}",
        color=0x5865F2
    )
    view = GiveawayView(message_id)
    for item in view.children:
        item.disabled = True

    if msg:
        try:
            await msg.edit(embed=embed, view=view)
        except Exception:
            pass

    try:
        if winners:
            await channel.send(f"🎉 Congrats {win_text} — you won **{title}**!")
        else:
            await channel.send("No valid entries.")
    except Exception:
        pass

    gw["ended"] = True
    GIVEAWAYS[mid] = gw
    save_giveaways(GIVEAWAYS)

# ================== META HELPERS ==================
async def db_get_meta(key: str) -> str | None:
    row = await db_fetchrow("SELECT value FROM muta_meta WHERE key=$1", key)
    return row["value"] if row and row["value"] is not None else None

async def db_set_meta(key: str, value: str) -> None:
    await db_execute("""
        INSERT INTO muta_meta(key, value)
        VALUES($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, key, value)

# ================== ECONOMY / LEVEL HELPERS ==================
async def ensure_user(uid: int):
    await db_execute("""
        INSERT INTO muta_users(user_id) VALUES($1)
        ON CONFLICT (user_id) DO NOTHING
    """, uid)

async def add_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("""
        UPDATE muta_users
        SET cash = cash + $2
        WHERE user_id = $1
        RETURNING cash
    """, uid, amount)
    return int(row["cash"])

async def deduct_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("""
        UPDATE muta_users
        SET cash = GREATEST(0, cash - $2)
        WHERE user_id = $1
        RETURNING cash
    """, uid, amount)
    return int(row["cash"])

async def earn_for_message(uid: int, now: datetime, msg_len: int) -> int:
    await ensure_user(uid)
    # cooldown + daily cap
    row = await db_fetchrow("SELECT last_earn_ts, today_earned, cash FROM muta_users WHERE user_id=$1", uid)
    last = row["last_earn_ts"]
    today_earned = int(row["today_earned"])

    # reset daily counter at local midnight
    local_midnight = datetime(now.year, now.month, now.day, tzinfo=TZ)
    if not last or last.astimezone(TZ) < local_midnight:
        today_earned = 0

    if last:
        delta = (now - last).total_seconds()
        if delta < EARN_COOLDOWN_SEC:
            return 0

    gain = EARN_PER_TICK + tier_bonus(msg_len)
    if DOUBLE_CASH:
        gain *= 2

    remaining = max(0, DAILY_CAP - today_earned)
    actual = min(gain, remaining)
    if actual <= 0:
        # just refresh last_earn_ts so cooldown still applies
        await db_execute("UPDATE muta_users SET last_earn_ts=$2 WHERE user_id=$1", uid, now)
        return 0

    await db_execute("""
        UPDATE muta_users
        SET cash = cash + $2,
            today_earned = CASE
                WHEN last_earn_ts IS NULL OR last_earn_ts < $3 THEN $2
                ELSE today_earned + $2
            END,
            last_earn_ts = $3
        WHERE user_id = $1
    """, uid, actual, now)

    # level-up roles
    await maybe_assign_level_role(uid)
    return actual

async def leaderboard_top(n: int = 10):
    rows = await db_fetch("""
        SELECT user_id, cash FROM muta_users
        ORDER BY cash DESC
        LIMIT $1
    """, n)
    return rows

async def monthly_reset():
    # zero balances & daily
    await db_execute("UPDATE muta_users SET cash=0, today_earned=0")
    # reset bug reward counters
    await db_execute("UPDATE muta_users SET bug_rewards_this_month=0")

async def can_bug_reward(uid: int) -> bool:
    row = await db_fetchrow("SELECT bug_rewards_this_month FROM muta_users WHERE user_id=$1", uid)
    if not row:
        await ensure_user(uid)
        return True
    return int(row["bug_rewards_this_month"]) < BUG_REWARD_LIMIT_PER_MONTH

async def mark_bug_reward(uid: int):
    await ensure_user(uid)
    await db_execute("""
        UPDATE muta_users
        SET bug_rewards_this_month = bug_rewards_this_month + 1
        WHERE user_id=$1
    """, uid)

# ===== Level roles (DB) =====
async def set_level_role(level: int, role_id: int):
    await db_execute("""
        INSERT INTO muta_level_roles(level, role_id) VALUES($1,$2)
        ON CONFLICT (level) DO UPDATE SET role_id = EXCLUDED.role_id
    """, level, role_id)

async def get_level_roles():
    rows = await db_fetch("SELECT level, role_id FROM muta_level_roles ORDER BY level ASC")
    return [(int(r["level"]), int(r["role_id"])) for r in rows]

async def maybe_assign_level_role(uid: int):
    # compute level from cash
    row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", uid)
    if not row:
        return
    cash = int(row["cash"])
    level = cash // CASH_PER_LEVEL

    mappings = await get_level_roles()
    if not mappings:
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    member = guild.get_member(uid)
    if not member:
        return

    # assign highest mapped role the user qualifies for
    elig = [role_id for lvl, role_id in mappings if level >= lvl]
    if not elig:
        return
    role_id = max(elig, key=lambda rid: rid)  # arbitrary tie-break; highest role id
    role = guild.get_role(role_id)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason=f"Reached level {level}")
        except Exception as e:
            print(f"[levels] add role failed: {e}")

# ================== MISC HELPERS ==================
def last_day_of_month(dt: datetime) -> int:
    nxt = (dt.replace(day=28) + timedelta(days=4))  # definitely next month
    return (nxt - timedelta(days=nxt.day)).day

TWEET_LINK_RE = re.compile(r"/" + re.escape(X_USERNAME) + r"/status/(\d+)")
def nitter_latest_id_from_html(text: str) -> str | None:
    m = TWEET_LINK_RE.search(text)
    return m.group(1) if m else None

def parse_duration_to_seconds(s: str):
    s = s.strip().lower()
    chunks = s.split()
    total = 0
    if len(chunks) > 1:
        for part in chunks:
            m = re.fullmatch(r"(\d+)\s*([dhm])", part)
            if not m: return None
            n, unit = int(m.group(1)), m.group(2)
            total += n*24*3600 if unit=="d" else n*3600 if unit=="h" else n*60
        return total
    m = re.fullmatch(r"(\d+)\s*([dhm])", s)
    if not m: return None
    n, unit = int(m.group(1)), m.group(2)
    return n*24*3600 if unit=="d" else n*3600 if unit=="h" else n*60

def humanize_seconds(sec: int) -> str:
    if sec % (24*3600) == 0: return f"{sec // (24*3600)}d"
    if sec % 3600 == 0:      return f"{sec // 3600}h"
    if sec % 60 == 0:        return f"{sec // 60}m"
    return f"{sec}s"

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
        super().__init__(timeout=300)
        self.target_id = target_id
        self.amount = amount

    @button(label="Yes (deduct)", style=discord.ButtonStyle.danger, emoji="⚠️", custom_id="pen_yes")
    async def yes_btn(self, interaction: discord.Interaction, _):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        new_bal = await deduct_cash(self.target_id, self.amount)
        await interaction.response.edit_message(content=f"✅ Deducted {self.amount}. New balance for <@{self.target_id}>: {new_bal}", view=None)

    @button(label="No", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="pen_no")
    async def no_btn(self, interaction: discord.Interaction, _):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        await interaction.response.edit_message(content="❎ Deduction cancelled.", view=None)

class BugApproveView(View):
    def __init__(self, reporter_id: int, description: str):
        super().__init__(timeout=600)
        self.reporter_id = reporter_id
        self.description = description

    @button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id="bug_yes")
    async def approve(self, interaction: discord.Interaction, _):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        if not await can_bug_reward(self.reporter_id):
            return await interaction.response.send_message("This user already reached this month’s bug reward limit.", ephemeral=True)
        await add_cash(self.reporter_id, BUG_REWARD_AMOUNT)
        await mark_bug_reward(self.reporter_id)
        await interaction.response.edit_message(content=f"🛠️ Bug approved. <@{self.reporter_id}> received **{BUG_REWARD_AMOUNT}** cash.\n> {self.description}", view=None)

    @button(label="Reject", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="bug_no")
    async def reject(self, interaction: discord.Interaction, _):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        await interaction.response.edit_message(content="Bug report rejected.", view=None)

# ================== COMMANDS EMBED ==================
def build_commands_embed(member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="📜 Mutapapa Bot Commands",
        description="Here’s a list of all commands available on this bot.",
        color=0x5865F2
    )

    # Everyone’s commands
    everyone = [
        ("!ping", "Check if the bot is alive. Responds with 'pong 🏓'."),
        ("!balance | !bal | !cashme | !mycash", "See how much Mutapapa Cash you have."),
        ("!leaderboard", "Shows the Top 10 richest users on the server."),
        (f"!cash <{DROP_WORD_COUNT} words>", "Claim a **cash drop** when it appears. Example: `!cash alpha bravo charlie delta`."),
        ("!bugreport <description>", "Report a Jailbreak bug. If approved by mods, you earn **350 cash** (max 2 per month)."),
        ("!countstatus", "Check the counting game progress: the next number & the goal."),
        ("!mylevel | !level", "Show your current level, cash, and how much until the next level."),
    ]

    # Admin / Mod commands (only shown to allowed roles or admins)
    admin = [
        ("!send <message>", "Make the bot send a message as itself."),
        ("!sendreact <message>", "Post a reaction-role message in the configured channel."),
        ("!gstart <duration> | <winners> | <title> | <desc>", "Start a giveaway. Examples: `!gstart 1h | 1 | 100 Robux | Join now!` or `!gstart 0h 1m | 1 | Flash Drop | Hurry!`."),
        ("!gend", "End the most recent active giveaway."),
        ("!greroll", "Reroll the most recent giveaway."),
        ("!countgoal <number>", "Set a new counting goal."),
        ("!countnext <number>", "Force the next expected number."),
        ("!countreset", "Reset counting back to 1."),
        ("!doublecash on|off", "Turn double-cash earnings on or off."),
        ("!addcash @user <amount> [reason] | !add @user <amount> [reason]", "Give cash to a user."),
        ("!removecash @user <amount> [reason] | !remove @user <amount> [reason]", "Remove cash from a user."),
        ("!rules on | !rules off", "Enable or disable the rule detector."),
        ("!setlevelrole <level> <@role|role_id>", "Map a level threshold to a role for auto-promotions."),
        ("!listlevelroles", "List current level→role mappings."),
    ]

    # Always show "Everyone"
    ev_lines = [f"**{name}**\n{desc}" for name, desc in everyone]
    embed.add_field(name="👥 Everyone", value="\n\n".join(ev_lines), inline=False)

    # Show admin section only to admins or members with an allowed role
    can_view_admin = (
        (member.guild_permissions.administrator) or
        any((r.id in COMMANDS_ADMIN_ROLE_IDS) for r in getattr(member, "roles", []))
    )

    if can_view_admin:
        ad_lines = [f"**{name}**\n{desc}" for name, desc in admin]
        embed.add_field(name="🛠️ Admin / Mods", value="\n\n".join(ad_lines), inline=False)

    embed.set_footer(text="Durations support d/h/m, e.g. '1d', '2h 30m', or '0h 1m'.")
    return embed

# ================== DISCORD EVENTS ==================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    # DB + web server
    await db_init()
    try:
        await start_webserver()
    except Exception as e:
        print(f"[web] start failed: {e}")
    # loops
    try:
        x_posts_loop.start()
    except Exception:
        pass
    try:
        drops_loop.start()
    except Exception:
        pass
    try:
        monthly_reset_loop.start()
    except Exception:
        pass
    print("All systems go.")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = (message.content or "").strip()
    clower  = content.lower()

    # help
    if clower in ("!commands", "!help"):
        await message.channel.send(embed=build_commands_embed(message.author))
        return

    async def delete_command_msg():
        try:
            await message.delete()
        except Exception:
            pass

    # ------------------ COMMANDS (run first) ------------------

    # ping
    if clower == "!ping":
        await message.channel.send("pong 🏓")
        await delete_command_msg()
        return

    # my level
    if clower in ("!mylevel", "!level"):
        await ensure_user(message.author.id)
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", message.author.id)
        cash = int(row["cash"]) if row else 0
        level = cash // CASH_PER_LEVEL
        need = ((level + 1) * CASH_PER_LEVEL) - cash
        await message.channel.send(f"🔼 {message.author.mention} level: **{level}** | cash: **{cash}** | next level in **{need}** cash")
        await delete_command_msg()
        return

    # rule detector toggle (admins or allowed roles)
    if clower.startswith("!rules "):
        can_toggle = (
            message.author.guild_permissions.administrator
            or any((r.id in COMMANDS_ADMIN_ROLE_IDS) for r in getattr(message.author, "roles", []))
        )
        if not can_toggle:
            await message.channel.send("❗ Mods/Admins only.")
            return
        arg = clower.split(maxsplit=1)[1].strip()
        if arg not in ("on","off"):
            await message.channel.send("Usage: `!rules on` or `!rules off`")
            return
        CONFIG["rule_detector_enabled"] = (arg == "on")
        save_config(CONFIG)
        await message.channel.send(f"🛰️ Rule detector **{arg.upper()}**.")
        await delete_command_msg()
        return

    # send as bot (admin)
    if clower.startswith("!send "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        text = content.split(" ", 1)[1].strip()
        if not text:
            await message.channel.send("Usage: `!send <message>`"); return
        await message.channel.send(text)
        await delete_command_msg()
        return

    # reaction-role: create tracked message (admin)
    if clower.startswith("!sendreact "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        rr_channel = message.guild.get_channel(REACTION_CHANNEL_ID)
        if not rr_channel:
            await message.channel.send("❗ REACTION_CHANNEL_ID is wrong or I can’t see that channel."); return
        body = content.split(" ", 1)[1].strip()
        sent = await rr_channel.send(body)
        for emoji in REACTION_ROLE_MAP.keys():
            try: await sent.add_reaction(emoji)
            except Exception: pass
        store = load_rr_store()
        store["message_id"] = sent.id
        store["channel_id"] = rr_channel.id
        save_rr_store(store)
        await message.channel.send(f"✅ Reaction-roles set on message ID `{sent.id}` in {rr_channel.mention}.")
        await delete_command_msg()
        return

    # giveaways
    if clower.startswith("!gstart "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        try:
            _, rest = content.split(" ", 1)
            parts = [p.strip() for p in rest.split("|")]
            dur_s = parse_duration_to_seconds(parts[0])        # supports "0h 1m"
            winners_count = int(parts[1])
            title = parts[2] if len(parts) > 2 else "Giveaway"
            desc  = parts[3] if len(parts) > 3 else ""
        except Exception:
            await message.channel.send(
                "Usage: `!gstart <duration> | <winners> | <title> | <description>`\n"
                "Examples: `!gstart 1h | 1 | 100 Robux | Press Enter to join!`  or  `!gstart 0h 1m | 1 | Flash Drop | Hurry!`"
            )
            return
        if not dur_s or dur_s <= 0 or winners_count < 1:
            await message.channel.send("❗ Bad duration or winners."); return
        ends_at = time() + dur_s
        embed = discord.Embed(title=title, description=desc, color=0x5865F2)
        embed.add_field(name="Duration", value=parts[0])
        embed.add_field(name="Winners", value=str(winners_count))
        embed.set_footer(text="Press Enter to join • View Participants to see who’s in")
        sent = await message.channel.send(embed=embed, view=GiveawayView(0))
        mid = str(sent.id)
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
        try:
            await sent.edit(view=GiveawayView(sent.id))
        except Exception:
            pass
        asyncio.create_task(schedule_giveaway_end(sent.id, ends_at))
        await delete_command_msg()
        return

    if clower == "!gend":
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        active = [(int(mid), gw) for mid, gw in GIVEAWAYS.items() if not gw.get("ended")]
        if not active:
            await message.channel.send("No active giveaways."); return
        latest_id = max(active, key=lambda t: t[0])[0]
        await end_giveaway(latest_id)
        await message.channel.send("✅ Giveaway ended.")
        await delete_command_msg()
        return

    if clower == "!greroll":
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        any_gw = [(int(mid), gw) for mid, gw in GIVEAWAYS.items()]
        if not any_gw:
            await message.channel.send("No giveaways found."); return
        latest_id = max(any_gw, key=lambda t: t[0])[0]
        gw = GIVEAWAYS.get(str(latest_id))
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
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        try:
            new_goal = int(content.split(maxsplit=1)[1])
            if new_goal < 1: raise ValueError
        except Exception:
            await message.channel.send("Usage: `!countgoal <positive integer>`"); return
        COUNT_STATE["goal"] = new_goal
        save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Goal set to **{new_goal}**.")
        await delete_command_msg()
        return

    if clower.startswith("!countnext "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        try:
            new_next = int(content.split(maxsplit=1)[1])
            if new_next < 1: raise ValueError
        except Exception:
            await message.channel.send("Usage: `!countnext <positive integer>`"); return
        COUNT_STATE["expected_next"] = new_next
        save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Next expected number set to **{new_next}**.")
        await delete_command_msg()
        return

    if clower == "!countreset":
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        COUNT_STATE["expected_next"] = 1
        save_count_state(COUNT_STATE)
        await message.channel.send("✅ Counter reset. Next expected number is **1**.")
        await delete_command_msg()
        return

    if clower == "!countstatus":
        st = COUNT_STATE
        await message.channel.send(f"🔢 Next: **{st.get('expected_next', 1)}** | Goal: **{st.get('goal', 67)}**")
        return

    # economy admin: add/remove cash
    if clower.startswith("!addcash") or clower.startswith("!add "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        if not message.mentions:
            await message.channel.send("Usage: `!addcash @user <amount> [reason]`"); return
        target = message.mentions[0]
        tail = content.split(maxsplit=1)[1] if " " in content else ""
        tail = tail.replace(str(target.mention), "").strip()
        parts = tail.split(maxsplit=1)
        try:
            amount = int(parts[0])
        except Exception:
            await message.channel.send("Usage: `!addcash @user <amount> [reason]`"); return
        reason = parts[1] if len(parts) > 1 else "Adjustment"
        new_bal = await add_cash(target.id, amount)
        await message.channel.send(f"➕ Added **{amount}** cash to {target.mention}. Reason: {reason} (bal: {new_bal})")
        await delete_command_msg()
        return

    if clower.startswith("!removecash") or clower.startswith("!remove "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        if not message.mentions:
            await message.channel.send("Usage: `!removecash @user <amount> [reason]`"); return
        target = message.mentions[0]
        tail = content.split(maxsplit=1)[1] if " " in content else ""
        tail = tail.replace(str(target.mention), "").strip()
        parts = tail.split(maxsplit=1)
        try:
            amount = int(parts[0])
        except Exception:
            await message.channel.send("Usage: `!removecash @user <amount> [reason]`"); return
        reason = parts[1] if len(parts) > 1 else "Adjustment"
        new_bal = await deduct_cash(target.id, amount)
        await message.channel.send(f"➖ Removed **{amount}** cash from {target.mention}. Reason: {reason} (bal: {new_bal})")
        await delete_command_msg()
        return

    # user balance / leaderboard
    if clower in ("!balance", "!bal", "!cashme", "!mycash"):
        await ensure_user(message.author.id)
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", message.author.id)
        await message.channel.send(f"💰 {message.author.mention} balance: **{row['cash']}** cash")
        await delete_command_msg()
        return

    if clower == "!leaderboard":
        rows = await leaderboard_top(10)
        if not rows:
            await message.channel.send("No data yet."); return
        lines = []
        for i, r in enumerate(rows, start=1):
            lines.append(f"**{i}.** <@{r['user_id']}> — {r['cash']}")
        embed = discord.Embed(title="🏆 Top 10", description="\n".join(lines), color=0xF1C40F)
        await message.channel.send(embed=embed)
        await delete_command_msg()
        return

    # double cash toggle (admin)
    if clower.startswith("!doublecash"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); return
        global DOUBLE_CASH
        arg = clower.split(maxsplit=1)[1].strip() if " " in clower else ""
        if arg in ("on","off"):
            DOUBLE_CASH = (arg == "on")
            await message.channel.send(f"💥 Double-cash **{arg.upper()}**.")
            await delete_command_msg()
            return
        await message.channel.send("Usage: `!doublecash on` or `!doublecash off`")
        return

    # bug report: !bugreport <short description>
    if clower.startswith("!bugreport "):
        desc = content.split(" ", 1)[1].strip()
        if len(desc) < 5:
            await message.channel.send("Please include a short description."); return
        channel = message.guild.get_channel(BUG_REVIEW_CHANNEL_ID)
        if not channel:
            await message.channel.send("Bug review channel not found."); return
        view = BugApproveView(message.author.id, desc)
        await channel.send(content=f"🐞 New bug report from {message.author.mention}:\n> {desc}", view=view)
        await message.channel.send("Submitted for review. A mod will approve or reject it.")
        await delete_command_msg()
        return

    # claim random cash drop: !cash <four words>
    if clower.startswith("!cash"):
        parts = content.split()
        if len(parts) >= (1 + DROP_WORD_COUNT):
            phrase = " ".join(p.lower() for p in parts[1:1+DROP_WORD_COUNT])
            row = await db_fetchrow("""
                SELECT id, amount FROM muta_drops
                WHERE phrase=$1 AND claimed_by IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """, phrase)
            if not row:
                await message.channel.send("That drop was already claimed or not found."); return
            drop_id = row["id"]; amount = row["amount"]
            await db_execute("""
                UPDATE muta_drops
                SET claimed_by=$1, claimed_at=NOW()
                WHERE id=$2 AND claimed_by IS NULL
            """, message.author.id, drop_id)
            new_bal = await add_cash(message.author.id, amount)
            await message.channel.send(f"💸 {message.author.mention} claimed **{amount}** cash! (bal: {new_bal})")
            await delete_command_msg()
            return
        else:
            await message.channel.send(f"Usage: `!cash <{DROP_WORD_COUNT} words from the embed>`")
            return

    # ------------------ NON-COMMANDS ------------------

    # Counting channel enforcement
    if message.channel.id == COUNT_CHANNEL_ID and not message.author.bot:
        if content.startswith("!"):
            return
        if not re.fullmatch(r"\d+", content):
            await try_delete(message); return
        n = int(content)
        expected = COUNT_STATE.get("expected_next", 1)
        if n != expected:
            await try_delete(message); return
        COUNT_STATE["expected_next"] = expected + 1
        save_count_state(COUNT_STATE)
        return

    # W/F/L auto-reaction
    if message.channel.id == WFL_CHANNEL_ID:
        t = clower
        has_wfl = (
            re.search(r"\bw\s*/\s*f\s*/\s*l\b", t) or
            re.search(r"\bwin\b.*\bfair\b.*\bloss\b", t) or
            re.search(r"\bw\s+f\s+l\b", t) or
            re.search(r"\bwfl\b", t) or
            re.search(r"\bwin\s*[- ]\s*fair\s*[- ]\s*loss\b", t)
        )
        if has_wfl:
            try:
                await message.add_reaction("🇼")
                await message.add_reaction("🇫")
                await message.add_reaction("🇱")
            except Exception as e:
                print(f"[wfl] failed to add reactions: {e}")

    # Earn cash for messages
    if message.channel.id in EARN_CHANNEL_IDS and not content.startswith("!"):
        now = datetime.now(tz=TZ)
        try:
            gained = await earn_for_message(message.author.id, now, len(content))
            if gained > 0:
                await maybe_assign_level_role(message.author.id)
        except Exception as e:
            print(f"[earn] error: {e}")

    # Rule / cross-trade detector
    if CONFIG.get("rule_detector_enabled", True) and (message.channel.id != MOD_LOG_CHANNEL_ID):
        if (not MONITORED_CHANNEL_IDS) or (message.channel.id in MONITORED_CHANNEL_IDS):
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
                    last = _last_report_by_user.get(message.author.id, 0)
                    if nowt - last >= _report_cooldown_sec:
                        _last_report_by_user[message.author.id] = nowt
                        modlog = message.guild.get_channel(MOD_LOG_CHANNEL_ID)
                        if modlog:
                            embed = discord.Embed(
                                title="⚠️ Possible Cross-Trading / Rule Violation",
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
async def on_member_join(member: discord.Member):
    if member.bot or member.guild.id != GUILD_ID:
        return
    guild = member.guild
    now = datetime.now(tz=TZ)
    if CONFIG.get("age_gate_enabled", True):
        acct_age_sec = (now - member.created_at.astimezone(TZ)).total_seconds()
        min_sec = int(CONFIG.get("min_account_age_sec", 7*24*3600))
        if acct_age_sec <= min_sec:
            try:
                dm = await member.create_dm()
                await dm.send(
                    "You have been kicked from the **Mutapapa Official Discord Server**.\n"
                    f"Reason: Your Discord account **must** be older than {humanize_seconds(min_sec)} to join."
                )
            except Exception:
                pass
            try:
                await member.kick(reason=f"Account younger than {humanize_seconds(min_sec)} (auto-moderation)")
            except discord.Forbidden:
                print("❗ Failed to kick: missing permission or role order.")
            modlog = guild.get_channel(MOD_LOG_CHANNEL_ID)
            if modlog:
                em = discord.Embed(
                    title="👟 Auto-kick: New Account",
                    description=(f"**User:** {member} (`{member.id}`)\n"
                                 f"**Account created:** {member.created_at:%Y-%m-%d %H:%M UTC}\n"
                                 f"**Age:** ~{int(acct_age_sec//86400)} day(s)\n"
                                 f"**Reason:** Account younger than {humanize_seconds(min_sec)}"),
                    color=0xE67E22
                )
                em.timestamp = discord.utils.utcnow()
                await modlog.send(embed=em)
            return

    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    if newcomer:
        try:
            await member.add_roles(newcomer, reason="New member")
        except discord.Forbidden:
            print("❗ Cannot assign @Newcomer (check role order/permissions).")

    ch = guild.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        embed = discord.Embed(
            title=f"Welcome to {guild.name}, {member.name}!",
            description=(f"Hey {member.mention}! Welcome to the **Mutapapa Official Discord Server!** "
                         "We hope you have a great time here!"),
            color=0x0089FF
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url=BANNER_URL)
        await ch.send(embed=embed)

# ================== REACTION ROLES (handlers) ==================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    if payload.user_id == (bot.user.id if bot.user else 0):
        return
    store = load_rr_store()
    if payload.message_id != store.get("message_id") or payload.channel_id != store.get("channel_id"):
        return
    emoji = str(payload.emoji)
    role_id = REACTION_ROLE_MAP.get(emoji)
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    role = guild.get_role(role_id)
    if not role: return
    member = guild.get_member(payload.user_id)
    if not member: return
    try:
        if role not in member.roles:
            await member.add_roles(role, reason="Reaction role add")
    except Exception as e:
        print(f"[rr] add error: {e}")

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    store = load_rr_store()
    if payload.message_id != store.get("message_id") or payload.channel_id != store.get("channel_id"):
        return
    emoji = str(payload.emoji)
    role_id = REACTION_ROLE_MAP.get(emoji)
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    role = guild.get_role(role_id)
    if not role: return
    member = guild.get_member(payload.user_id)
    if not member: return
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Reaction role remove")
    except Exception as e:
        print(f"[rr] remove error: {e}")

# ================== BACKGROUND LOOPS ==================
@tasks.loop(minutes=2)
async def x_posts_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    if not ch:
        return

    cache = load_x_cache()
    last_guid = cache.get("last_guid")

    # 1) Try RSS first
    feeds = [X_RSS_URL] + [u for u in X_RSS_FALLBACKS if u != X_RSS_URL]
    announced = False
    try:
        xml = None
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            for url in feeds:
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            xml = await resp.text()
                            break
                except Exception:
                    pass

        if xml:
            try:
                root = ET.fromstring(xml)
                channel = root.find("./channel")
                items = channel.findall("item") if channel is not None else []
                if items:
                    item = items[0]
                    guid = (item.findtext("guid") or item.findtext("link") or "").strip()
                    title = (item.findtext("title") or "").strip()
                    link  = (item.findtext("link")  or "").strip()
                    if guid and guid != last_guid:
                        x_link = nitter_to_x(link) if link else None
                        embed = discord.Embed(
                            title=f"New X post by @{X_USERNAME}",
                            description=title[:4000] or "New post",
                            url=x_link,
                            color=0x1DA1F2
                        )
                        await ch.send(embed=embed)
                        save_x_cache({"last_guid": guid})
                        announced = True
            except Exception:
                pass
    except Exception:
        pass

    if announced:
        return

    # 2) Fallback: parse the Nitter HTML via a read-only text mirror.
    try:
        mirror_url = f"https://r.jina.ai/http://nitter.net/{X_USERNAME}"
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            async with session.get(mirror_url, timeout=10) as resp:
                if resp.status != 200:
                    return
                text = await resp.text()
    except Exception:
        return

    tweet_id = nitter_latest_id_from_html(text)
    if not tweet_id:
        return

    guid = f"nitter:{tweet_id}"
    if guid == last_guid:
        return

    x_link = f"https://x.com/{X_USERNAME}/status/{tweet_id}"
    embed = discord.Embed(
        title=f"New X post by @{X_USERNAME}",
        description="(Auto-detected from Nitter page)",
        url=x_link,
        color=0x1DA1F2
    )
    try:
        await ch.send(embed=embed)
        save_x_cache({"last_guid": guid})
    except Exception:
        pass

@tasks.loop(minutes=5)
async def drops_loop():
    """Ensure up to 4 drops per local day in CASH_DROP_CHANNEL_ID."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch:
        return

    # Guard: ensure table exists
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
        return  # if DB isn’t ready yet, just try again next tick

    now = datetime.now(tz=TZ)
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)

    try:
        rows = await db_fetch("""
            SELECT COUNT(*) AS c FROM muta_drops
            WHERE channel_id=$1 AND created_at >= $2
        """, CASH_DROP_CHANNEL_ID, start)
    except Exception:
        return

    today_count = rows[0]["c"] if rows else 0
    if today_count >= DROPS_PER_DAY:
        return

    phrase = four_words()
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
    except Exception:
        try:
            await msg.delete()
        except Exception:
            pass
        return

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
                desc = None
                if rows:
                    desc = "\n".join(
                        f"**{idx}.** <@{r['user_id']}> — {r['cash']} cash"
                        for idx, r in enumerate(rows, start=1)
                    )
                for cid in SEASON_RESET_ANNOUNCE_CHANNEL_IDS:
                    ch = guild.get_channel(cid)
                    if not ch:
                        continue
                    if desc:
                        embed = discord.Embed(
                            title="🏁 Season ended — Final Top 10",
                            description=desc,
                            color=0xF39C12
                        )
                        await ch.send(embed=embed)
                    await ch.send("🧹 Balances reset. New season starts now — good luck!")
        except Exception:
            pass

# ================== RUN ==================
def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN env var is missing")
    bot.run(token)

if __name__ == "__main__":
    main()