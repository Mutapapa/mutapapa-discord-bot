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
MOD_LOG_CHANNEL_ID = 1413297073348018299

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

# Channels you want the cross-trade detector to monitor
MONITORED_CHANNEL_IDS = [
    1411930067994411139, 1411930091109224479, 1411930638260502638,
    1411930689460240395, 1411931034026643476
]

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

# Banner image (Discord CDN links with ?ex expire eventually; replace later with a stable URL if needed)
BANNER_URL = "https://cdn.discordapp.com/attachments/1411930091109224479/1413654925602459769/Welcome_to_the_Mutapapa_Official_Discord_Server_Image.png?ex=68bcb83e&is=68bb66be&hm=f248257c26608d0ee69b8baab82f62aea768f15f090ad318617e68350fe3b5ac&"

# Penalty approvals go here (Yes/No buttons)
PENALTY_CHANNEL_ID = 1414124795418640535

# Cash drop announcements channel
CASH_DROP_CHANNEL_ID = 1414120740327788594

# Optional: nice places to send bot announcements/leaderboard
CASH_ANNOUNCE_CHANNEL_ID   = 1414124134903844936
LEADERBOARD_CHANNEL_ID     = 1414124214956593242

# Age Gate defaults (persisted to config.json)
CONFIG_FILE = "config.json"

# Join probation persistence
DATA_FILE = "join_times.json"

# Giveaways
GIVEAWAYS_FILE = "giveaways.json"

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
DAILY_CAP         = 2000         # does not include random drops
DOUBLE_CASH       = False        # toggled by !doublecash on/off

# random drops (4 per local day)
DROPS_PER_DAY     = 4
DROP_AMOUNT       = 225
DROP_WORD_COUNT   = 4  # "!cash <word1> <word2> <word3> <word4>"

# bug reward
BUG_REWARD_AMOUNT = 350
BUG_REWARD_LIMIT_PER_MONTH = 2  # per user
BUGS_CHANNEL_ID = 0  # <-- set your real "bugs" channel ID when ready

# levels: +1 level per 3000 cash (cosmetic; you’ll map roles yourself later)
CASH_PER_LEVEL = 3000

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
    return load_json(CONFIG_FILE, {"age_gate_enabled": True, "min_account_age_sec": 7 * 24 * 3600})

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

def load_data():
    return load_json(DATA_FILE, {})

def save_data(d):
    save_json(DATA_FILE, d)

def load_giveaways():
    data = load_json(GIVEAWAYS_FILE, {})
    return data if isinstance(data, dict) else {}

def save_giveaways(d):
    save_json(GIVEAWAYS_FILE, d)

CONFIG      = load_config()
join_times  = load_data()
COUNT_STATE = load_count_state()
GIVEAWAYS   = load_giveaways()

# ================== DISCORD CLIENT ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# ================== DB (Supabase Postgres via asyncpg) ==================
DB_URL = os.getenv("SUPABASE_URL")
_pool: asyncpg.Pool | None = None

async def db_init():
    global _pool
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)

async def db_fetchrow(query, *args):
    async with _pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def db_execute(query, *args):
    async with _pool.acquire() as con:
        return await con.execute(query, *args)

async def db_fetch(query, *args):
    async with _pool.acquire() as con:
        return await con.fetch(query, *args)

# Ensure user row exists
async def ensure_user(uid: int):
    await db_execute("""
        INSERT INTO muta_users(user_id)
        VALUES($1)
        ON CONFLICT (user_id) DO NOTHING
    """, uid)

# Reset "today" counter if day changed in Edmonton
def same_local_day(ts: datetime, now: datetime) -> bool:
    return ts.astimezone(TZ).date() == now.astimezone(TZ).date()

# Earn with cooldown, cap, and optional double
async def earn_for_message(uid: int, now: datetime) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("""
        SELECT cash, last_earn_ts, today_earned
        FROM muta_users WHERE user_id=$1
    """, uid)
    cash, last_ts, today = row["cash"], row["last_earn_ts"], row["today_earned"]

    # reset daily tracker if needed
    if last_ts and not same_local_day(last_ts, now):
        today = 0

    # cooldown
    if last_ts and (now - last_ts).total_seconds() < EARN_COOLDOWN_SEC:
        return 0

    # cap
    if today >= DAILY_CAP:
        return 0

    amt = EARN_PER_TICK * (2 if DOUBLE_CASH else 1)
    # don't exceed cap
    if today + amt > DAILY_CAP:
        amt = max(0, DAILY_CAP - today)
    if amt == 0:
        return 0

    new_cash = cash + amt
    new_today = today + amt

    await db_execute("""
        UPDATE muta_users
        SET cash=$1, last_earn_ts=$2, today_earned=$3
        WHERE user_id=$4
    """, new_cash, now, new_today, uid)

    # level-ups (every 3000)
    old_level = (cash // CASH_PER_LEVEL)
    new_level = (new_cash // CASH_PER_LEVEL)
    if new_level > old_level:
        # announce quietly? You can add role-assign here later.
        pass

    return amt

# Deduct (for penalty) with floor at 0
async def deduct_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", uid)
    cash = row["cash"]
    new_cash = max(0, cash - amount)
    await db_execute("UPDATE muta_users SET cash=$1 WHERE user_id=$2", new_cash, uid)
    return new_cash

# Add cash (drops, bug reward), no cap
async def add_cash(uid: int, amount: int) -> int:
    await ensure_user(uid)
    row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", uid)
    cash = row["cash"]
    new_cash = cash + amount
    await db_execute("UPDATE muta_users SET cash=$1 WHERE user_id=$2", new_cash, uid)
    return new_cash

# Bug reward limit tracking
async def can_bug_reward(uid: int, now: datetime) -> bool:
    await ensure_user(uid)
    row = await db_fetchrow("SELECT bug_rewards_this_month FROM muta_users WHERE user_id=$1", uid)
    cnt = row["bug_rewards_this_month"]
    return cnt < BUG_REWARD_LIMIT_PER_MONTH

async def mark_bug_reward(uid: int):
    await ensure_user(uid)
    await db_execute("""
        UPDATE muta_users SET bug_rewards_this_month = bug_rewards_this_month + 1
        WHERE user_id=$1
    """, uid)

# Reset month (cash to 0, today_earned 0, bug count 0)
async def monthly_reset():
    await db_execute("""
        UPDATE muta_users
        SET cash=0, today_earned=0, bug_rewards_this_month=0
    """)

# Leaderboard (top 10)
async def leaderboard_top(limit=10):
    rows = await db_fetch("""
        SELECT user_id, cash FROM muta_users
        ORDER BY cash DESC, user_id ASC
        LIMIT $1
    """, limit)
    return rows

# ================== TEXT NORMALIZATION / DETECTOR ==================
LEET_MAP = str.maketrans({"$":"s","@":"a","0":"o","1":"i","3":"e","5":"s","7":"t"})
def normalize_text(s: str) -> str:
    s = s.lower().translate(LEET_MAP)
    s = re.sub(r"[\W_]+", " ", s)
    return " ".join(s.split())

BUY_SELL_WORDS = {
    "buy","buying","wtb","purchase","sell","selling","wts","forsale","for sale",
    "trade","trading","lf","looking","looking for"
}
CROSSTRADE_HINTS = {
    "cross trade","cross trading","x trade","x trading","jb for","jailbreak for",
    "trading jailbreak for","gag","grow a garden","stb","sab","steal a brainrot","brainrot",
    "adopt me","blox fruits","pls donate","psx","pet sim","paypal","cashapp","venmo",
    "etransfer","e transfer","gift card","robux for money","r$ for","nitro for cash",
    "real money","irl money","dm me for cash","pay with","sell for $","buy for $"
}
CROSSTRADE_PATTERNS = [
    re.compile(r"\b(jb|jailbreak)\s*(for|4)\s+\w+", re.I),
    re.compile(r"\btrading\s+(jb|jailbreak)\s*(for|4)\s+\w+", re.I),
    re.compile(r"\bbuy(ing)?\b.*\bfor\b.*\b(cash|paypal|gift\s*card|venmo|etransfer|e\s*transfer)\b", re.I),
    re.compile(r"\bsell(ing)?\b.*\bfor\b.*\b(cash|paypal|gift\s*card|venmo|etransfer|e\s*transfer)\b", re.I),
]
_report_cooldown_sec = 30
_last_report_by_user = {}

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
        self._entered: set[int] = set()  # in-memory anti-double-click for this session only

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

        # Grey out the Enter button just for that user (Discord can’t disable per-user; we keep anti-spam in memory)
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
    if len(parts) == 0:
        winners = []
    else:
        winners = random.sample(parts, k=min(winners_count, len(parts)))

    title = gw.get("title") or "Giveaway"
    desc  = gw.get("desc") or ""

    # inline end message (edited)
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

    # optional channel announce
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

# ================== HELPERS ==================
def parse_duration_to_seconds(s: str):
    s = s.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([dhm])", s)
    if not m: return None
    n, unit = int(m.group(1)), m.group(2)
    return n*24*3600 if unit=="d" else n*3600 if unit=="h" else n*60 if unit=="m" else None

def humanize_seconds(sec: int) -> str:
    if sec % (24*3600) == 0: return f"{sec // (24*3600)}d"
    if sec % 3600 == 0:      return f"{sec // 3600}h"
    if sec % 60 == 0:        return f"{sec // 60}m"
    return f"{sec}s"

async def try_delete(msg: discord.Message):
    try:
        await msg.delete()
    except Exception:
        pass

def nitter_to_x(url: str) -> str:
    return url.replace("https://nitter.net", "https://x.com")

def four_words():
    # silly 4-word phrase
    words = ["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly",
             "kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango",
             "ultra","vivid","wax","xeno","yodel","zen"]
    return " ".join(random.choice(words) for _ in range(DROP_WORD_COUNT))

# ================== VIEWS (Penalty prompt) ==================
class PenaltyView(View):
    def __init__(self, target_id: int, amount: int):
        super().__init__(timeout=300)
        self.target_id = target_id
        self.amount = amount

    @button(label="Yes (deduct)", style=discord.ButtonStyle.danger, emoji="⚠️", custom_id="pen_yes")
    async def yes_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        new_bal = await deduct_cash(self.target_id, self.amount)
        await interaction.response.edit_message(content=f"✅ Deducted {self.amount}. New balance for <@{self.target_id}>: {new_bal}", view=None)

    @button(label="No", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="pen_no")
    async def no_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        await interaction.response.edit_message(content="❎ Deduction cancelled.", view=None)

# ================== DISCORD EVENTS ==================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} | latency={bot.latency:.3f}s")
    # DB
    await db_init()

    # Web server for YT push
    asyncio.create_task(start_webserver())
    public_url = os.getenv("PUBLIC_BASE_URL","").rstrip("/")
    if public_url:
        asyncio.create_task(websub_subscribe(public_url))
    else:
        print("[yt-webhook] PUBLIC_BASE_URL not set; skipping subscription.")

    # reattach giveaway views and timers
    for mid, gw in list(GIVEAWAYS.items()):
        if not gw.get("ended") and gw.get("channel_id"):
            bot.add_view(GiveawayView(int(mid)))
            ends_at = gw.get("ends_at")
            if ends_at:
                asyncio.create_task(schedule_giveaway_end(int(mid), ends_at))

    promote_loop.start()
    x_posts_loop.start()
    drops_loop.start()
    monthly_reset_loop.start()

# ================== MESSAGE HANDLING ==================
@bot.event
async def on_message(message: discord.Message):
    if not message.guild or message.guild.id != GUILD_ID:
        return

    # Counting channel: numbers only and exact sequence
    if message.channel.id == COUNT_CHANNEL_ID and not message.author.bot:
        if message.content.startswith("!"):  # allow commands here; handle below
            pass
        else:
            txt = message.content.strip()
            if not re.fullmatch(r"\d+", txt):
                await try_delete(message); return
            n = int(txt)
            expected = COUNT_STATE.get("expected_next", 1)
            if n != expected:
                await try_delete(message); return
            COUNT_STATE["expected_next"] = expected + 1
            save_count_state(COUNT_STATE)

    # economy: earn on messages in eligible channels (cooldown + cap)
    if (not message.author.bot) and (message.channel.id in EARN_CHANNEL_IDS):
        now = datetime.now(tz=TZ)
        earned = await earn_for_message(message.author.id, now)
        # (silent; no spam)

    # Below: admin/user commands
    content = message.content.strip()
    clower  = content.lower()

    # ---------- BASIC ----------
    if clower == "!ping":
        await message.channel.send("pong 🏓")
        await try_delete(message)
        return

    # ---------- ECONOMY ----------
    if clower == "!cash":
        # If this is *not* a drop claim with phrase, just show balance instead.
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", message.author.id)
        bal = row["cash"] if row else 0
        await message.channel.send(f"💰 <@{message.author.id}> balance: **{bal}** cash")
        await try_delete(message)
        return

    if clower.startswith("!cash "):
        # Try claim a drop: "!cash <four words>"
        phrase = content[6:].strip().lower()
        if len(phrase.split()) != DROP_WORD_COUNT:
            await message.channel.send("❗ Format: `!cash <4-words-phrase>` to claim a drop.")
            await try_delete(message); return
        # find an unclaimed recent drop in this channel with that phrase
        row = await db_fetchrow("""
            SELECT id, amount FROM muta_drops
            WHERE channel_id=$1 AND phrase=$2 AND claimed_by IS NULL
            ORDER BY created_at DESC LIMIT 1
        """, message.channel.id, phrase)
        if not row:
            await message.channel.send("❗ No active cash drop matches that phrase.")
            await try_delete(message); return

        drop_id, amt = row["id"], row["amount"]
        # atomic claim
        async with _pool.acquire() as con:
            async with con.transaction():
                did = await con.fetchval("""
                    UPDATE muta_drops
                    SET claimed_by=$1
                    WHERE id=$2 AND claimed_by IS NULL
                    RETURNING id
                """, message.author.id, drop_id)
                if not did:
                    await message.channel.send("❗ Someone already claimed that drop.")
                    await try_delete(message); return
        new_bal = await add_cash(message.author.id, amt)
        await message.channel.send(f"🎁 <@{message.author.id}> claimed **{amt}** cash! New balance: **{new_bal}**")
        await try_delete(message)
        return

    if clower == "!cashbal":
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", message.author.id)
        bal = row["cash"] if row else 0
        await message.channel.send(f"💰 <@{message.author.id}> balance: **{bal}** cash")
        await try_delete(message); return

    if clower == "!leaderboard":
        rows = await leaderboard_top(10)
        if not rows:
            await message.channel.send("No data yet.")
            await try_delete(message); return
        desc = []
        for idx, r in enumerate(rows, start=1):
            desc.append(f"**{idx}.** <@{r['user_id']}> — {r['cash']} cash")
        embed = discord.Embed(title="🏆 Top 10 (This Month)", description="\n".join(desc), color=0xF1C40F)
        await message.channel.send(embed=embed)
        await try_delete(message); return

    # Double cash on/off (announce)
    if clower.startswith("!doublecash"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        arg = clower.split(maxsplit=1)[1] if len(clower.split()) > 1 else ""
        global DOUBLE_CASH
        if arg in ("on", "enable", "start"):
            DOUBLE_CASH = True
            await message.channel.send("⚡ **Double cash enabled!**")
        elif arg in ("off", "disable", "stop"):
            DOUBLE_CASH = False
            await message.channel.send("⛔ **Double cash disabled.**")
        else:
            await message.channel.send("Usage: `!doublecash on|off`")
        await try_delete(message); return

    # Penalize (prompts Yes/No in PENALTY_CHANNEL_ID and shows current balance)
    if clower.startswith("!penalize "):
        if not message.author.guild_permissions.manage_messages:
            await message.channel.send("❗ Mods only."); await try_delete(message); return
        if not message.mentions:
            await message.channel.send("Usage: `!penalize @user [reason...]`")
            await try_delete(message); return
        target = message.mentions[0]
        row = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", target.id)
        bal = row["cash"] if row else 0
        ch = message.guild.get_channel(PENALTY_CHANNEL_ID)
        if not ch:
            await message.channel.send("❗ PENALTY_CHANNEL_ID invalid.")
            await try_delete(message); return
        reason = content.split(maxsplit=2)[2] if len(content.split()) >= 3 else "Rule violation"
        view = PenaltyView(target.id, 1500)
        await ch.send(f"Penalty request: Deduct **1500** from <@{target.id}> (bal: {bal}) — Reason: {reason}", view=view)
        await message.channel.send("✅ Posted penalty prompt.")
        await try_delete(message); return

    # Grant bug reward (with approval buttons) — optional, post in BUGS_CHANNEL_ID or current channel
    if clower.startswith("!bugreward "):
        if not message.author.guild_permissions.manage_messages:
            await message.channel.send("❗ Mods only."); await try_delete(message); return
        if not message.mentions:
            await message.channel.send("Usage: `!bugreward @user`")
            await try_delete(message); return
        target = message.mentions[0]
        now = datetime.now(tz=TZ)
        if not await can_bug_reward(target.id, now):
            await message.channel.send("❗ This user has hit the monthly bug-report reward limit.")
            await try_delete(message); return
        # reuse PenaltyView logic with a positive flow (we’ll just pay immediately for simplicity)
        new_bal = await add_cash(target.id, BUG_REWARD_AMOUNT)
        await mark_bug_reward(target.id)
        await message.channel.send(f"🐞 Granted **{BUG_REWARD_AMOUNT}** to <@{target.id}> for a valid bug report. New bal: {new_bal}")
        await try_delete(message); return

    # ---------- ADMIN: SEND AS BOT ----------
    if clower.startswith("!send "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            await try_delete(message); return
        text = content.split(" ", 1)[1].strip()
        if not text:
            await message.channel.send("Usage: `!send <message>`")
            await try_delete(message); return
        await message.channel.send(text)
        await try_delete(message); return

    # ---------- REACTION-ROLE LAUNCH ----------
    if clower.startswith("!sendreact "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        rr_channel = message.guild.get_channel(REACTION_CHANNEL_ID)
        if not rr_channel:
            await message.channel.send("❗ REACTION_CHANNEL_ID invalid.")
            await try_delete(message); return
        body = content.split(" ", 1)[1].strip()
        sent = await rr_channel.send(body)
        for emoji in REACTION_ROLE_MAP.keys():
            try: await sent.add_reaction(emoji)
            except: pass
        store = load_rr_store()
        store["message_id"] = sent.id
        store["channel_id"] = rr_channel.id
        save_rr_store(store)
        await message.channel.send(f"✅ Reaction-roles set on message ID `{sent.id}` in {rr_channel.mention}.")
        await try_delete(message); return

    # ---------- AGE GATE ----------
    if clower == "!showminage":
        await message.channel.send(
            f"Age-gate is **{'ON' if CONFIG.get('age_gate_enabled', True) else 'OFF'}**, "
            f"min age = **{humanize_seconds(CONFIG.get('min_account_age_sec', 7*24*3600))}**."
        )
        await try_delete(message); return

    if clower.startswith("!agegate "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        arg = clower.split(maxsplit=1)[1]
        if arg in ("on","off"):
            CONFIG["age_gate_enabled"] = (arg == "on")
            save_config(CONFIG)
            await message.channel.send(f"✅ Age-gate turned **{arg.upper()}**.")
        else:
            await message.channel.send("Usage: `!agegate on` or `!agegate off`")
        await try_delete(message); return

    if clower.startswith("!setminage"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `!setminage <number>d|h|m`  e.g. `!setminage 10d`")
            await try_delete(message); return
        sec = parse_duration_to_seconds(parts[1])
        if sec is None or sec <= 0:
            await message.channel.send("❗ Invalid. Use like `!setminage 7d` or `!setminage 24h`.")
            await try_delete(message); return
        CONFIG["min_account_age_sec"] = int(sec)
        save_config(CONFIG)
        await message.channel.send(f"✅ Minimum account age set to **{humanize_seconds(sec)}**.")
        await try_delete(message); return

    # ---------- GIVEAWAYS ----------
    if clower.startswith("!gstart "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        # format: !gstart <duration> | <winners> | <title> | <description...>
        try:
            _, rest = message.content.split(" ", 1)
            parts = [p.strip() for p in rest.split("|")]
            dur_s = parse_duration_to_seconds(parts[0])
            winners_count = int(parts[1])
            title = parts[2]
            desc = parts[3] if len(parts) > 3 else ""
        except Exception:
            await message.channel.send(
                "Usage: `!gstart <duration> | <winners> | <title> | <description>`\n"
                "e.g. `!gstart 2h | 1 | Nitro Classic | Click Enter to join!`"
            )
            await try_delete(message); return
        if not dur_s or dur_s <= 0 or winners_count < 1:
            await message.channel.send("❗ Bad duration or winners.")
            await try_delete(message); return

        ends_at = time() + dur_s
        embed = discord.Embed(title=title, description=desc, color=0x5865F2)
        embed.add_field(name="Duration", value=parts[0])
        embed.add_field(name="Winners", value=str(winners_count))
        embed.set_footer(text="Press Enter to join • View Participants to see who’s in")
        temp = await message.channel.send(embed=embed, view=GiveawayView(0))
        mid = str(temp.id)
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
        view = GiveawayView(temp.id)
        try: await temp.edit(view=view)
        except: pass
        asyncio.create_task(schedule_giveaway_end(temp.id, ends_at))
        await try_delete(message); return

    if clower.startswith("!gend"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        # no id required: end most recent active
        mid = None
        for k, gw in sorted(GIVEAWAYS.items(), key=lambda kv: int(kv[0]), reverse=True):
            if not gw.get("ended"):
                mid = int(k)
                break
        if not mid:
            await message.channel.send("No active giveaways.")
            await try_delete(message); return
        await end_giveaway(mid)
        await message.channel.send("✅ Ended (or already ended).")
        await try_delete(message); return

    if clower.startswith("!greroll"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only."); await try_delete(message); return
        # reroll most recent giveaway (ended or not)
        mid = None
        for k, gw in sorted(GIVEAWAYS.items(), key=lambda kv: int(kv[0]), reverse=True):
            mid = int(k)
            break
        if not mid:
            await message.channel.send("No giveaways found.")
            await try_delete(message); return
        gw = GIVEAWAYS.get(str(mid))
        if gw:
            gw["ended"] = False
            save_giveaways(GIVEAWAYS)
        await end_giveaway(mid)
        await message.channel.send("✅ Rerolled.")
        await try_delete(message); return

    # ---------- MOD-LOG TEST ----------
    if clower == "!modlogtest":
        ch = message.guild.get_channel(MOD_LOG_CHANNEL_ID)
        if ch:
            e = discord.Embed(
                title="Mod-log test",
                description=f"Triggered by {message.author.mention} in {message.channel.mention}",
                color=0x2ECC71
            )
            e.timestamp = discord.utils.utcnow()
            e.set_footer(text=f"Channel ID: {message.channel.id}")
            await ch.send(embed=e)
            await message.channel.send("✅ Sent a test embed to mod-log.")
        else:
            await message.channel.send("❗ MOD_LOG_CHANNEL_ID wrong or bot can’t see that channel.")
        await try_delete(message); return

    # ---------- W/F/L auto-reactions ----------
    if message.channel.id == WFL_CHANNEL_ID:
        t = message.content.lower()
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

    # ---------- Cross-trade detector ----------
    if message.channel.id != MOD_LOG_CHANNEL_ID and (not message.author.bot):
        if not MONITORED_CHANNEL_IDS or (message.channel.id in MONITORED_CHANNEL_IDS):
            raw = message.content or ""
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
        try: await member.add_roles(newcomer, reason="New member")
        except discord.Forbidden:
            print("❗ Cannot assign @Newcomer (check role order/permissions).")

    # welcome embed
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
    guild = bot.get_guild(payload.guild_id); 
    if not guild: return
    role = guild.get_role(role_id); 
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
    guild = bot.get_guild(payload.guild_id); 
    if not guild: return
    role = guild.get_role(role_id); 
    if not role: return
    member = guild.get_member(payload.user_id)
    if not member: return
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Reaction role remove")
    except Exception as e:
        print(f"[rr] remove error: {e}")

# ================== BACKGROUND LOOPS ==================
@tasks.loop(minutes=5)
async def promote_loop():
    # (kept from your earlier auto-promotion after 3 days)
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    member_role = guild.get_role(MEMBER_ROLE_ID)
    if not newcomer or not member_role: return
    # NOTE: join_times storage removed earlier for simplicity (auto-promo could be role-based elsewhere)
    # Keeping placeholder — feel free to remove this loop if not using probation anymore.

@tasks.loop(minutes=2)
async def x_posts_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    if not ch: return

    # try primary first, then fallbacks
    feeds = [X_RSS_URL] + [u for u in X_RSS_FALLBACKS if u != X_RSS_URL]
    xml = None
    async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as session:
        for url in feeds:
            try:
                async with session.get(url, timeout=12) as resp:
                    if resp.status == 200:
                        xml = await resp.text()
                        break
                    else:
                        print(f"[x] rss status {resp.status} from {url}")
            except Exception as e:
                print(f"[x] fetch error from {url}: {e}")

    if not xml:
        return

    # parse simple RSS
    try:
        root = ET.fromstring(xml)
        channel = root.find("./channel")
        items = channel.findall("item") if channel is not None else []
        if not items: return
    except Exception as e:
        print(f"[x] parse error: {e}")
        return

    cache = load_x_cache()
    last_guid = cache.get("last_guid")
    new_items = []
    for it in items:
        guid = (it.findtext("guid") or it.findtext("link") or "").strip()
        if not guid:
            continue
        if guid == last_guid:
            break
        new_items.append(it)

    if not new_items:
        return

    new_items.reverse()
    latest_guid = last_guid
    for it in new_items:
        title = (it.findtext("title") or "").strip()
        link  = (it.findtext("link") or "").strip()
        pubdate = (it.findtext("pubDate") or "").strip()
        x_link = nitter_to_x(link) if link else None
        embed = discord.Embed(
            title=f"New X post by @{X_USERNAME}",
            description=title[:4000] or "New post",
            url=x_link,
            color=0x1DA1F2
        )
        if pubdate:
            embed.set_footer(text=pubdate)
        try:
            await ch.send(embed=embed)
        except Exception:
            pass
        guid = (it.findtext("guid") or it.findtext("link") or "").strip()
        if guid:
            latest_guid = guid
    if latest_guid and latest_guid != last_guid:
        save_x_cache({"last_guid": latest_guid})
        print(f"[x] announced {len(new_items)} new post(s)")

@tasks.loop(minutes=5)
async def drops_loop():
    """Ensure up to 4 drops per local day in CASH_DROP_CHANNEL_ID."""
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch: return

    # Count today's drops
    now = datetime.now(tz=TZ)
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    rows = await db_fetch("""
        SELECT COUNT(*) AS c FROM muta_drops
        WHERE channel_id=$1 AND created_at >= $2
    """, CASH_DROP_CHANNEL_ID, start)
    today_count = rows[0]["c"] if rows else 0

    if today_count >= DROPS_PER_DAY:
        return

    # Post a new drop
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

    await db_execute("""
        INSERT INTO muta_drops(channel_id, message_id, phrase, amount, created_at)
        VALUES($1,$2,$3,$4, NOW())
    """, CASH_DROP_CHANNEL_ID, msg.id, phrase.lower(), DROP_AMOUNT)

@tasks.loop(minutes=1)
async def monthly_reset_loop():
    """At 23:59 Edmonton time, reset all balances for the new month."""
    now = datetime.now(tz=TZ)
    # If it’s 23:59 exactly, reset (simple check with 1-min loop)
    if now.hour == 23 and now.minute == 59:
        print("[season] monthly reset running…")
        await monthly_reset()
        # Optional: announce top 10 frozen standings before reset (if you want)
        try:
            guild = bot.get_guild(GUILD_ID)
            ch = guild.get_channel(LEADERBOARD_CHANNEL_ID) if guild else None
            if ch:
                rows = await leaderboard_top(10)
                if rows:
                    desc = []
                    for idx, r in enumerate(rows, start=1):
                        desc.append(f"**{idx}.** <@{r['user_id']}> — {r['cash']} cash")
                    embed = discord.Embed(
                        title="🏁 Season ended — Final Top 10",
                        description="\n".join(desc),
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