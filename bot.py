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
MOD_LOG_CHANNEL_ID = 1413297073348018299
SEASON_RESET_ANNOUNCE_CHANNEL_IDS = [1414000088790863874, 1411931034026643476, 1411930067994411139, 1411930091109224479, 1411930689460240395, 1414120740327788594]


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

# Penalty approvals go here (Yes/No buttons) — also used for bug approvals
PENALTY_CHANNEL_ID = 1414124795418640535

# Cash drop announcements channel
CASH_DROP_CHANNEL_ID = 1414120740327788594

# Optional: nice places to send bot announcements/leaderboard
CASH_ANNOUNCE_CHANNEL_ID   = 1414124134903844936
LEADERBOARD_CHANNEL_ID     = 1414124214956593242

# Age Gate defaults (persisted to config.json)
CONFIG_FILE = "config.json"

# Giveaways (persisted)
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
BUGS_CHANNEL_ID = 0  # <— set your real "bugs" submission channel ID when you create it

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

def load_giveaways():
    data = load_json(GIVEAWAYS_FILE, {})
    return data if isinstance(data, dict) else {}

def save_giveaways(d):
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
from urllib.parse import urlparse

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

# ================== HELPERS ==================

# --- simple meta storage for one-off flags (season resets, etc.) ---
async def db_get_meta(key: str) -> str | None:
    row = await db_fetchrow("select value from muta_meta where key=$1", key)
    return row["value"] if row and row["value"] is not None else None

async def db_set_meta(key: str, value: str) -> None:
    await db_execute("""
        insert into muta_meta(key, value)
        values($1, $2)
        on conflict (key) do update set value = excluded.value
    """, key, value)

def last_day_of_month(dt: datetime) -> int:
    # dt is timezone-aware (TZ). Compute the last day number (28–31).
    nxt = (dt.replace(day=28) + timedelta(days=4))  # definitely next month
    return (nxt - timedelta(days=nxt.day)).day

import html
TWEET_LINK_RE = re.compile(r"/" + re.escape(X_USERNAME) + r"/status/(\d+)")
def nitter_latest_id_from_html(text: str) -> str | None:
    """
    Given the plain-text mirror of a Nitter user page, return the first tweet ID we find.
    We look for '/<user>/status/<digits>'.
    """
    m = TWEET_LINK_RE.search(text)
    return m.group(1) if m else None

def parse_duration_to_seconds(s: str):
    # supports "10m", "1h", "2d" and also "0h 1m", "1h 30m"
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

# ================== DISCORD EVENTS ==================
@bot.event
async def on_ready():

async def db_init():



    global _pool
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)

    # --- AUTO-MIGRATIONS (creates tables if they don't exist) ---
    async with _pool.acquire() as con:
        # Users table
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_users (
            user_id BIGINT PRIMARY KEY,
            cash INTEGER NOT NULL DEFAULT 0,
            last_earn_ts TIMESTAMPTZ,
            today_earned INTEGER NOT NULL DEFAULT 0,
            bug_rewards_this_month INTEGER NOT NULL DEFAULT 0
        );
        """)

        # Drops table
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

        # Helpful indexes
        await con.execute("""
        CREATE INDEX IF NOT EXISTS idx_muta_drops_created_at
            ON muta_drops (created_at);
        """)

# ================== MESSAGE HANDLING ==================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = (message.content or "").strip()
    clower  = content.lower()

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
        channel = message.guild.get_channel(PENALTY_CHANNEL_ID)
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
            # try claim latest matching, unclaimed
            row = await db_fetchrow("""
                SELECT id, amount FROM muta_drops
                WHERE phrase=$1 AND claimed_by IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """, phrase)
            if not row:
                await message.channel.send("That drop was already claimed or not found."); return
            drop_id = row["id"]; amount = row["amount"]
            # mark claimed (avoid race)
            await db_execute("""
                UPDATE muta_drops
                SET claimed_by=$1, claimed_at=NOW()
                WHERE id=$2 AND claimed_by IS NULL
            """, message.author.id, drop_id)
            # add money
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
            return  # commands handled above
        if not re.fullmatch(r"\d+", content):
            await try_delete(message); return
        n = int(content)
        expected = COUNT_STATE.get("expected_next", 1)
        if n != expected:
            await try_delete(message); return
        COUNT_STATE["expected_next"] = expected + 1
        save_count_state(COUNT_STATE)
        return

    # W/F/L auto-reaction (only there)
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

    # Earn cash for messages (channels you allow), with cooldown/daily cap and tier bonus
    if message.channel.id in EARN_CHANNEL_IDS and not content.startswith("!"):
        now = datetime.now(tz=TZ)
        try:
            gained = await earn_for_message(message.author.id, now, len(content))
            if gained > 0:
                # optionally, very quiet: comment out to make it silent
                # await message.add_reaction("💰")
                pass
        except Exception as e:
            print(f"[earn] error: {e}")

    # Cross-trade detector (after commands; only in monitored channels)
    if message.channel.id != MOD_LOG_CHANNEL_ID:
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

    # 1) Try RSS first (some Nitter instances disable it; we fall back if so)
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
                    # newest first in RSS
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
    # Using r.jina.ai avoids Cloudflare & JS; returns plain text of the page.
    # Example URL it fetches: https://r.jina.ai/http://nitter.net/<user>
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

    # Post a basic embed linking to the canonical X URL
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
@tasks.loop(minutes=5)
async def drops_loop():
    """Ensure up to 4 drops per local day in CASH_DROP_CHANNEL_ID."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch:
        return

    # Guard: ensure table exists in case this loop beat db_init() migrations
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
        # If the insert failed for a transient reason, delete the message so users don't see a dead drop
        try:
            await msg.delete()
        except Exception:
            pass
        return

@tasks.loop(minutes=1)
@tasks.loop(minutes=1)
@tasks.loop(minutes=1)
@tasks.loop(minutes=1)
async def monthly_reset_loop():
    """Reset ONLY at the end of the month: last day 23:59 America/Edmonton."""
    now = datetime.now(tz=TZ)
    next_minute = now + timedelta(minutes=1)
    if now.hour == 23 and now.minute == 59 and next_minute.day == 1:
        print("[season] monthly reset running…")
        # Grab final standings before wiping
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