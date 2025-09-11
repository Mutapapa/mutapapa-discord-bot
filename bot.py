# bot.py
import os
import asyncio
import json
import re
import hmac
import hashlib
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
from discord import app_commands
from discord.ui import View, button

# ================== CORE CONFIG (edit IDs) ==================
GUILD_ID = 1411205177880608831

WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID   = 1411957261009555536
MEMBER_ROLE_ID     = 1411938410041708585
MOD_LOG_CHANNEL_ID = 1413297073348018299

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
    "📺": 1412989373556850829,
    "🔔": 1412993171670958232,
    "✖️": 1414001344297172992,
    "🎉": 1412992931148595301,
}
RR_STORE_FILE = "reaction_msg.json"

# W/F/L channel
WFL_CHANNEL_ID = 1411931034026643476

# Counting
COUNT_CHANNEL_ID = 1414051875329802320
COUNT_STATE_FILE = "count_state.json"

# Cross-trade monitor
MONITORED_CHANNEL_IDS = [
    1411930067994411139, 1411930091109224479, 1411930638260502638,
    1411930689460240395, 1411931034026643476
]

# YouTube announce (Shorts too)
YT_CHANNEL_ID          = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID        = 1412989373556850829
YT_CALLBACK_PATH       = "/yt/webhook"
YT_HUB                 = "https://pubsubhubbub.appspot.com"
YT_SECRET              = "mutapapa-youtube"
YT_CACHE_FILE          = "yt_last_video.json"

# X (Twitter)
X_USERNAME = "Real_Mutapapa"
X_RSS_FALLBACKS = [
    f"https://nitter.net/{X_USERNAME}/rss",
    f"https://nitter.mailt.buzz/{X_USERNAME}/rss",
    f"https://nitter.poast.org/{X_USERNAME}/rss",
]
X_RSS_URL = os.getenv("X_RSS_URL") or X_RSS_FALLBACKS[0]
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_PING_ROLE_ID        = 1414001344297172992
X_CACHE_FILE          = "x_last_item.json"

# Bug review + penalties
BUGS_REVIEW_CHANNEL_ID = 1414124214956593242
PENALTY_CHANNEL_ID     = 1414124795418640535

# Drops + level-up announcements
CASH_DROP_CHANNEL_ID   = 1414120740327788594
LEVEL_UP_CHANNEL_ID    = 1414124134903844936

# “mods see more in /help”
HELP_MOD_ROLE_IDS = {1413663966349234320, 1411940485005578322, 1413991410901713088}

# Edmonton time
TZ = ZoneInfo("America/Edmonton")

# ================== ECONOMY ==================
EARN_CHANNEL_IDS = [
    1411930638260502638,1411486271464935456,1413297073348018299,1411935203953217566,
    1411435784250331288,1412144563144888452,1411931216608755782,1414000975680897128,
    1411433941403177054,1411931171671117854,1411946767414591538,1413999346592256050,
    1414001588091093052
]
EARN_COOLDOWN_SEC = 180
EARN_PER_TICK     = 200
DAILY_CAP         = 2000
DOUBLE_CASH       = False

def tier_bonus(n: int) -> int:
    if n <= 9: return 0
    if n <= 49: return 50
    if n <= 99: return 80
    return 100

# Drops
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
ROLE_NAME_MAP = {
    ROLE_ROOKIE:"Rookie",
    ROLE_SQUAD:"Squad Member",
    ROLE_SPECIALIST:"Specialist",
    ROLE_OPERATIVE:"Operative",
    ROLE_LEGEND:"Legend",
}
LEVEL_ROLE_IDS = set(ROLE_NAME_MAP.keys())

# ================== PERSIST HELPERS ==================
CONFIG_FILE = "config.json"
GIVEAWAYS_FILE = "giveaways.json"

def load_json(path, default):
    try:
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path,"w",encoding="utf-8") as f: json.dump(data,f)

def load_config():
    return load_json(CONFIG_FILE, {"age_gate_enabled": True, "min_account_age_sec": 7*24*3600})

def save_config(cfg): save_json(CONFIG_FILE, cfg)
def load_rr_store():  return load_json(RR_STORE_FILE, {})
def save_rr_store(d): save_json(RR_STORE_FILE, d)
def load_x_cache():   return load_json(X_CACHE_FILE, {})
def save_x_cache(d):  save_json(X_CACHE_FILE, d)
def load_count_state():
    d = load_json(COUNT_STATE_FILE, {"expected_next":1,"goal":67})
    d.setdefault("expected_next",1); d.setdefault("goal",67); return d
def save_count_state(d): save_json(COUNT_STATE_FILE, d)
def load_yt_cache():  return load_json(YT_CACHE_FILE, {})
def save_yt_cache(d): save_json(YT_CACHE_FILE, d)

CONFIG      = load_config()
COUNT_STATE = load_count_state()

# ================== DISCORD CLIENT ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot  = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ================== DB (Supabase via asyncpg) ==================
DB_URL = os.getenv("SUPABASE_DB_URL","").strip()
if not DB_URL:
    raise RuntimeError("SUPABASE_DB_URL missing (postgresql://...)")

if urlparse(DB_URL).scheme.lower() not in ("postgresql","postgres"):
    raise RuntimeError("SUPABASE_DB_URL must start with postgresql:// or postgres://")

_pool: asyncpg.Pool | None = None

async def db_init():
    global _pool
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)
    async with _pool.acquire() as con:
        await con.execute("""CREATE TABLE IF NOT EXISTS muta_meta(key TEXT PRIMARY KEY, value TEXT);""")
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_users(
            user_id BIGINT PRIMARY KEY,
            cash BIGINT NOT NULL DEFAULT 0,
            last_earn_ts TIMESTAMPTZ,
            today_earned BIGINT NOT NULL DEFAULT 0,
            bug_rewards_this_month INTEGER NOT NULL DEFAULT 0,
            activity_points BIGINT NOT NULL DEFAULT 0
        );""")
        await con.execute("""
        CREATE TABLE IF NOT EXISTS muta_drops(
            id BIGSERIAL PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL UNIQUE,
            phrase TEXT NOT NULL,
            amount INTEGER NOT NULL,
            claimed_by BIGINT,
            claimed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""")

async def db_fetchrow(q,*a):
    async with _pool.acquire() as con: return await con.fetchrow(q,*a)
async def db_execute(q,*a):
    async with _pool.acquire() as con: return await con.execute(q,*a)

# meta helpers
async def db_get_meta(key: str):
    r = await db_fetchrow("SELECT value FROM muta_meta WHERE key=$1", key)
    return r["value"] if r and r["value"] is not None else None

async def db_set_meta(key: str, value: str):
    await db_execute("INSERT INTO muta_meta(key,value) VALUES($1,$2) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", key, value)

# ================== ECONOMY / USERS ==================
async def ensure_user(uid:int):
    await db_execute("INSERT INTO muta_users(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", uid)

async def add_cash(uid:int, amt:int)->int:
    await ensure_user(uid)
    r = await db_fetchrow("UPDATE muta_users SET cash=cash+$1 WHERE user_id=$2 RETURNING cash", amt, uid)
    return int(r["cash"]) if r else 0

async def can_bug_reward(uid:int)->bool:
    await ensure_user(uid)
    now = datetime.now(tz=TZ); key = f"bug_month:{now.year}-{now.month}"
    if await db_get_meta(key) != "ok":
        await db_execute("UPDATE muta_users SET bug_rewards_this_month=0")
        await db_set_meta(key,"ok")
    r = await db_fetchrow("SELECT bug_rewards_this_month FROM muta_users WHERE user_id=$1", uid)
    return bool(r) and int(r["bug_rewards_this_month"]) < BUG_REWARD_LIMIT_PER_MONTH

async def mark_bug_reward(uid:int):
    await db_execute("UPDATE muta_users SET bug_rewards_this_month=bug_rewards_this_month+1 WHERE user_id=$1", uid)

async def earn_for_message(uid:int, now:datetime, msg_len:int, guild:discord.Guild|None, author_id:int):
    await ensure_user(uid)
    r = await db_fetchrow("SELECT last_earn_ts,today_earned,activity_points FROM muta_users WHERE user_id=$1", uid)
    last = r["last_earn_ts"]; today = int(r["today_earned"] or 0); pts = int(r["activity_points"] or 0)
    if last is not None and last.astimezone(TZ).date() != now.date(): today = 0
    if today >= DAILY_CAP: return 0
    if last is not None and (now-last).total_seconds() < EARN_COOLDOWN_SEC: return 0
    gain = EARN_PER_TICK + tier_bonus(msg_len)
    if DOUBLE_CASH: gain *= 2
    grant = min(gain, max(0, DAILY_CAP-today))
    await db_execute(
        "UPDATE muta_users SET cash=cash+$1,last_earn_ts=$2,today_earned=$3,activity_points=$4 WHERE user_id=$5",
        grant, now, today+grant, pts+grant, uid
    )
    # roles check
    if guild:
        m = guild.get_member(author_id)
        if m: await check_and_assign_levels(m, pts+grant)
    return grant

# ================== LEVELS ==================
def role_name_from_id(rid:int)->str: return ROLE_NAME_MAP.get(rid, f"Role {rid}")
def next_threshold(points:int):
    for rid, need in sorted(ACTIVITY_THRESHOLDS, key=lambda t: t[1]):
        if points < need: return rid, need - points
    return None, None

async def announce_level_up(guild:discord.Guild, member:discord.Member, rid:int):
    ch = guild.get_channel(LEVEL_UP_CHANNEL_ID)
    if ch:
        try:
            await ch.send(f"{member.mention} reached the **{role_name_from_id(rid)}** role!")
        except Exception: pass

async def check_and_assign_levels(member:discord.Member, points:int):
    to_add=[]
    for rid, need in ACTIVITY_THRESHOLDS:
        role = member.guild.get_role(rid)
        if role and points >= need and role not in member.roles:
            to_add.append(role)
    if to_add:
        try:
            await member.add_roles(*to_add, reason=f"Activity points = {points}")
            await announce_level_up(member.guild, member, to_add[-1].id)
        except Exception as e:
            print(f"[levels] add_roles error: {e}")

# ================== UTILS ==================
def humanize_seconds(sec:int)->str:
    if sec%(24*3600)==0: return f"{sec//(24*3600)}d"
    if sec%3600==0:      return f"{sec//3600}h"
    if sec%60==0:        return f"{sec//60}m"
    return f"{sec}s"

def normalize_text(s:str)->str:
    s = s.lower()
    s = re.sub(r"[_*~`>]", " ", s)
    return re.sub(r"\s+"," ",s).strip()

BUY_SELL_WORDS = {"cross-trade","cross trade","blackmarket","bm","robux","paypal","venmo","crypto","btc","eth","real money","sell robux","buy robux","cashapp"}
CROSSTRADE_HINTS = {"dm me to buy","selling for cash","buying with cash","pay real money","outside discord"}
CROSSTRADE_PATTERNS = [
    re.compile(r"sell(?:ing)?\s+\d+\s*robux", re.I),
    re.compile(r"buy(?:ing)?\s+\d+\s*robux", re.I),
    re.compile(r"\b(pp|paypal|btc|eth|cashapp|venmo)\b", re.I),
]

def four_words():
    words = ["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly","kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango","ultra","vivid","wax","xeno","yodel","zen"]
    return " ".join(random.choice(words) for _ in range(DROP_WORD_COUNT))

# ================== AIOHTTP (YouTube Webhook) ==================
app = web.Application()

async def yt_webhook_handler(request: web.Request):
    if request.method == "GET":
        return web.Response(text=request.query.get("hub.challenge") or "ok")

    body = await request.read()

    if YT_SECRET:
        sig = request.headers.get("X-Hub-Signature","")
        try:
            alg, hexdigest = sig.split("=",1)
            digestmod = {"sha1": hashlib.sha1, "sha256": hashlib.sha256}.get(alg.lower())
            if digestmod:
                mac = hmac.new(YT_SECRET.encode(), body, digestmod)
                if not hmac.compare_digest(mac.hexdigest(), hexdigest):
                    return web.Response(status=400, text="bad signature")
        except Exception:
            return web.Response(status=400, text="bad signature")

    try:
        root = ET.fromstring(body.decode("utf-8",errors="ignore"))
        ns = {"atom":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
        entry = root.find("atom:entry", ns)
        if entry is None: return web.Response(text="no entry")
        vid   = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title",   default="", namespaces=ns)
    except Exception as e:
        print(f"[yt] parse error: {e}")
        return web.Response(text="ok")

    if vid:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            ch   = guild.get_channel(YT_ANNOUNCE_CHANNEL_ID)
            role = guild.get_role(YT_PING_ROLE_ID)
            if ch and role:
                await ch.send(
                    content=f"{title}\n\n{role.mention} Mutapapa just released a new video called: **{title}** Click to watch it!\nhttps://youtu.be/{vid}",
                    allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False)
                )
                print(f"[yt] announced {vid}")
    return web.Response(text="ok")

async def health(_): return web.Response(text="ok")

app.add_routes([
    web.get(YT_CALLBACK_PATH, yt_webhook_handler),
    web.post(YT_CALLBACK_PATH, yt_webhook_handler),
    web.get("/health", health),
])

runner = web.AppRunner(app)
async def start_webserver():
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT","8080")))
    await site.start()
    print(f"[web] listening on {YT_CALLBACK_PATH}")

# ================== SLASH COMMANDS (EPHEMERAL) ==================
def build_commands_embed(member: discord.Member)->discord.Embed:
    show_mod = any((r.id in HELP_MOD_ROLE_IDS) for r in getattr(member,"roles",[])) or member.guild_permissions.administrator
    e = discord.Embed(title="📜 Mutapapa Bot Commands", description="Replies are **private** (ephemeral).", color=0x5865F2)
    everyone = [
        ("/help, /commands","Show this menu."),
        ("/balance","See your cash."),
        ("/leaderboard","Top 10 richest users."),
        (f"/cash phrase:<{DROP_WORD_COUNT} words>","Claim a cash drop."),
        ("/bugreport description:<text>","Report a bug (mods approve for rewards)."),
        ("/countstatus","Counting game status."),
        ("/level","See your activity points & next level."),
    ]
    e.add_field(name="👥 Everyone", value="\n".join(f"**{n}** — {d}" for n,d in everyone), inline=False)
    if show_mod:
        e.add_field(name="🛠️ Mods", value="**/levelup user:<@> level:<name|1-5|role>** — Set a user’s level.", inline=False)
    return e

@tree.command(name="help", description="Show commands (private)")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_commands_embed(interaction.user), ephemeral=True)

@tree.command(name="commands", description="Alias of /help (private)")
async def commands_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_commands_embed(interaction.user), ephemeral=True)

@tree.command(name="balance", description="See your cash (private)")
async def balance_cmd(interaction: discord.Interaction):
    await ensure_user(interaction.user.id)
    r = await db_fetchrow("SELECT cash FROM muta_users WHERE user_id=$1", interaction.user.id)
    await interaction.response.send_message(f"💰 Your balance: **{r['cash']}** cash", ephemeral=True)

@tree.command(name="leaderboard", description="Top 10 (private)")
async def leaderboard_cmd(interaction: discord.Interaction):
    rows = await _pool.fetch("SELECT user_id, cash FROM muta_users ORDER BY cash DESC LIMIT 10")
    if not rows:
        return await interaction.response.send_message("No data yet.", ephemeral=True)
    lines = [f"**{i}.** <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows,1)]
    await interaction.response.send_message(embed=discord.Embed(title="🏆 Top 10", description="\n".join(lines), color=0xF1C40F), ephemeral=True)

@tree.command(name="countstatus", description="Counting status (private)")
async def countstatus_cmd(interaction: discord.Interaction):
    s = COUNT_STATE
    await interaction.response.send_message(f"🔢 Next: **{s.get('expected_next',1)}** | Goal: **{s.get('goal',67)}**", ephemeral=True)

@tree.command(name="bugreport", description="Report a bug (private)")
@app_commands.describe(description="Short description")
async def bugreport_cmd(interaction: discord.Interaction, description: str):
    if len(description.strip()) < 5:
        return await interaction.response.send_message("Please add a bit more detail.", ephemeral=True)
    ch = interaction.guild.get_channel(BUGS_REVIEW_CHANNEL_ID) if interaction.guild else None
    if not ch:
        return await interaction.response.send_message("Bug review channel not found.", ephemeral=True)
    await ch.send(content=f"🐞 New bug report from {interaction.user.mention}:\n> {description}", view=BugApproveView(interaction.user.id, description))
    await interaction.response.send_message("Submitted for review. A mod will approve or reject it.", ephemeral=True)

@tree.command(name="cash", description=f"Claim a cash drop using the {DROP_WORD_COUNT} words (private)")
@app_commands.describe(phrase=f"Exactly {DROP_WORD_COUNT} words from the drop")
async def cash_cmd(interaction: discord.Interaction, phrase: str):
    parts = phrase.split()
    if len(parts) != DROP_WORD_COUNT:
        return await interaction.response.send_message(f"Please enter **{DROP_WORD_COUNT} words** exactly.", ephemeral=True)
    phrase_norm = " ".join(p.lower() for p in parts)
    row = await db_fetchrow("""
        SELECT id, amount FROM muta_drops
        WHERE phrase=$1 AND claimed_by IS NULL
        ORDER BY created_at DESC LIMIT 1
    """, phrase_norm)
    if not row:
        return await interaction.response.send_message("That drop was already claimed or not found.", ephemeral=True)
    await db_execute("UPDATE muta_drops SET claimed_by=$1, claimed_at=NOW() WHERE id=$2 AND claimed_by IS NULL", interaction.user.id, row["id"])
    new_bal = await add_cash(interaction.user.id, int(row["amount"]))
    await interaction.response.send_message(f"💸 You claimed **{row['amount']}**! New balance: **{new_bal}**", ephemeral=True)

@tree.command(name="level", description="See your activity progress (private)")
async def level_cmd(interaction: discord.Interaction):
    await ensure_user(interaction.user.id)
    r = await db_fetchrow("SELECT activity_points FROM muta_users WHERE user_id=$1", interaction.user.id)
    pts = int(r["activity_points"] or 0)
    nxt, remain = next_threshold(pts)
    nxt_text = "You’re at the top. 🔥" if nxt is None else f"Next: **{ROLE_NAME_MAP[nxt]}** in **{remain}** points."
    await interaction.response.send_message(f"**Activity points:** **{pts}**\n{nxt_text}", ephemeral=True)

@tree.command(name="levelup", description="(Mods) Set a user's level role (private)")
@app_commands.describe(user="User to promote", level="Role name, 1-5, or role mention text")
async def levelup_cmd(interaction: discord.Interaction, user: discord.Member, level: str):
    if not (interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("❗ Mods/Admins only.", ephemeral=True)

    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("Guild only.", ephemeral=True)

    # Determine target role id
    target_id = None
    m = re.search(r"<@&(\d+)>", level)
    if m:
        rid = int(m.group(1))
        if rid in LEVEL_ROLE_IDS: target_id = rid
    if not target_id and re.fullmatch(r"[1-5]", level.strip()):
        idx = int(level.strip()); target_id = sorted(ACTIVITY_THRESHOLDS, key=lambda t:t[1])[idx-1][0]
    if not target_id:
        low = level.strip().lower()
        for rid, name in ROLE_NAME_MAP.items():
            if name.lower() == low or low in name.lower():
                target_id = rid; break

    if not target_id:
        return await interaction.response.send_message("Couldn’t match that level. Use a level name, 1–5, or mention the role.", ephemeral=True)

    role = guild.get_role(target_id)
    if not role:
        return await interaction.response.send_message("That level role doesn’t exist here.", ephemeral=True)

    try:
        if role not in user.roles:
            await user.add_roles(role, reason=f"Manual level set by {interaction.user}")
            await announce_level_up(guild, user, target_id)
        await interaction.response.send_message(f"Set {user.mention} to **{ROLE_NAME_MAP[target_id]}**.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("I can’t add that role (check my role position/permissions).", ephemeral=True)

# ================== BUTTON VIEWS ==================
class BugApproveView(View):
    def __init__(self, reporter_id:int, description:str):
        super().__init__(timeout=600)
        self.reporter_id = reporter_id
        self.description = description

    @button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, i: discord.Interaction, _):
        if not i.user.guild_permissions.manage_messages:
            return await i.response.send_message("Mods only.", ephemeral=True)
        if not await can_bug_reward(self.reporter_id):
            return await i.response.send_message("This user is at the monthly reward limit.", ephemeral=True)
        await add_cash(self.reporter_id, BUG_REWARD_AMOUNT)
        await mark_bug_reward(self.reporter_id)
        await i.response.edit_message(content=f"🛠️ Bug approved. <@{self.reporter_id}> +**{BUG_REWARD_AMOUNT}**\n> {self.description}", view=None)

    @button(label="Reject", style=discord.ButtonStyle.secondary, emoji="❌")
    async def reject(self, i: discord.Interaction, _):
        if not i.user.guild_permissions.manage_messages:
            return await i.response.send_message("Mods only.", ephemeral=True)
        await i.response.edit_message(content="Bug report rejected.", view=None)

# ================== EVENTS / LOOPS ==================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await db_init()
    await start_webserver()
    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Slash commands synced.")
    except Exception as e:
        print(f"Slash sync error: {e}")
    yt_poll_loop.start()
    drops_loop.start()
    x_posts_loop.start()
    monthly_reset_loop.start()
    newcomer_promo_loop.start()

# YouTube poll fallback (also catches Shorts)
@tasks.loop(minutes=3)
async def yt_poll_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(YT_ANNOUNCE_CHANNEL_ID)
    role = guild.get_role(YT_PING_ROLE_ID)
    if not ch or not role: return
    cache = load_yt_cache()
    last = cache.get("last_video_id")
    feed = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as s:
            async with s.get(feed, timeout=10) as r:
                if r.status != 200: return
                xml = await r.text()
        root = ET.fromstring(xml)
        ns = {"atom":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
        entry = root.find("atom:entry", ns)
        if not entry: return
        vid   = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title",   default="", namespaces=ns)
        if not vid or vid == last: return
        await ch.send(
            content=f"{title}\n\n{role.mention} Mutapapa just released a new video called: **{title}** Click to watch it!\nhttps://youtu.be/{vid}",
            allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False)
        )
        save_yt_cache({"last_video_id": vid})
    except Exception as e:
        print(f"[yt poll] {e}")

# Drops schedule (persisted)
def _today_key(now:datetime)->str: return now.strftime("%Y%m%d")
async def _get_or_build_today_drop_schedule(now:datetime)->dict:
    meta_key = f"drops_schedule:{_today_key(now)}"
    raw = await db_get_meta(meta_key)
    if raw:
        try:
            d = json.loads(raw)
            if isinstance(d,dict) and "times" in d and "created" in d: return d
        except Exception: pass
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    end   = start + timedelta(days=1)
    count = random.choice([3,4])
    seconds = sorted(random.sample(range(int((end-start).total_seconds())), count))
    times = [int(start.timestamp()) + s for s in seconds]
    sched = {"times":times, "created":[False]*count}
    await db_set_meta(meta_key, json.dumps(sched))
    return sched

async def _mark_drop_created(now:datetime, sched:dict, idx:int):
    sched["created"][idx] = True
    await db_set_meta(f"drops_schedule:{_today_key(now)}", json.dumps(sched))

@tasks.loop(seconds=45)
async def drops_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch: return
    now = datetime.now(tz=TZ)
    sched = await _get_or_build_today_drop_schedule(now)
    for i, ts in enumerate(sched["times"]):
        if sched["created"][i]: continue
        if time() >= ts:
            phrase = four_words()
            embed = discord.Embed(title="[Cash] Cash drop!", description=f"Type `/cash phrase: {phrase}` to collect **{DROP_AMOUNT}** cash!", color=0x2ECC71)
            try:
                msg = await ch.send(embed=embed)
                await db_execute("INSERT INTO muta_drops(channel_id,message_id,phrase,amount,created_at) VALUES($1,$2,$3,$4,NOW())",
                                 CASH_DROP_CHANNEL_ID, msg.id, phrase.lower(), DROP_AMOUNT)
                await _mark_drop_created(now, sched, i)
            except Exception:
                try: await msg.delete()
                except Exception: pass
            finally:
                break

# X posts announce (new only)
def nitter_to_x(url:str)->str: return url.replace("https://nitter.net", "https://x.com")
@tasks.loop(minutes=2)
async def x_posts_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    ping = guild.get_role(X_PING_ROLE_ID)
    if not ch or not ping: return
    cache = load_x_cache(); last = cache.get("last_tweet_id")
    feeds = [X_RSS_URL] + [u for u in X_RSS_FALLBACKS if u != X_RSS_URL]
    try:
        xml=None
        async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as s:
            for url in feeds:
                try:
                    async with s.get(url, timeout=10) as r:
                        if r.status==200:
                            xml = await r.text(); break
                except Exception: pass
        if xml:
            root = ET.fromstring(xml)
            channel = root.find("./channel")
            items = channel.findall("item") if channel is not None else []
            if items:
                item = items[0]
                title = (item.findtext("title") or "").strip()
                link  = (item.findtext("link")  or "").strip()
                m = re.search(r"/status/(\d+)", link); tid = m.group(1) if m else None
                if tid and tid != last:
                    await ch.send(
                        content=f"{ping.mention} **{title or 'New post on X'}**\nMutapapa just posted something on X (Formerly Twitter)!  Click to check it out!\n{nitter_to_x(link)}",
                        allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False)
                    )
                    save_x_cache({"last_tweet_id": tid})
                    return
    except Exception: pass
    # Fallback quick scrape
    try:
        async with aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as s:
            async with s.get(f"https://r.jina.ai/http://nitter.net/{X_USERNAME}", timeout=10) as r:
                if r.status!=200: return
                text = await r.text()
        m = re.search(r"/"+re.escape(X_USERNAME)+r"/status/(\d+)", text); tid = m.group(1) if m else None
        if tid and tid != last:
            await ch.send(
                content=f"{ping.mention} Mutapapa just posted something on X (Formerly Twitter)!  Click to check it out!\nhttps://x.com/{X_USERNAME}/status/{tid}",
                allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False)
            )
            save_x_cache({"last_tweet_id": tid})
    except Exception: pass

# Monthly reset
@tasks.loop(minutes=1)
async def monthly_reset_loop():
    now = datetime.now(tz=TZ); next_min = now + timedelta(minutes=1)
    if now.hour==23 and now.minute==59 and next_min.day==1:
        await db_execute("UPDATE muta_users SET cash=0, today_earned=0")

# Newcomer -> Member after 3 days
@tasks.loop(minutes=10)
async def newcomer_promo_loop():
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    member   = guild.get_role(MEMBER_ROLE_ID)
    if not newcomer or not member: return
    for m in guild.members:
        if newcomer in m.roles and not m.bot and m.joined_at and (discord.utils.utcnow()-m.joined_at).total_seconds() >= 3*24*3600:
            try:
                await m.remove_roles(newcomer, reason="Auto-promo after 3 days")
                await m.add_roles(member,   reason="Auto-promo after 3 days")
            except Exception as e:
                print(f"[promo] {e}")

# ================== MESSAGE HANDLING (for earning + moderation) ==================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    content = (message.content or "").strip()
    clower  = content.lower()

    # Counting enforcement
    if message.channel.id == COUNT_CHANNEL_ID:
        if content.startswith("/"): return
        if not re.fullmatch(r"\d+", content):
            try: await message.delete()
            except Exception: pass
            return
        n = int(content); expected = COUNT_STATE.get("expected_next",1)
        if n != expected:
            try: await message.delete()
            except Exception: pass
            return
        COUNT_STATE["expected_next"] = expected + 1
        save_count_state(COUNT_STATE)
        return

    # WFL auto-reactions
    if message.channel.id == WFL_CHANNEL_ID:
        t = clower
        has = (re.search(r"\bw\s*/\s*f\s*/\s*l\b",t) or re.search(r"\bwfl\b",t) or re.search(r"\bwin\s*[- ]\s*fair\s*[- ]\s*loss\b",t))
        if has:
            for e in ("🇼","🇫","🇱"):
                try: await message.add_reaction(e)
                except Exception: pass

    # Earn for messages
    if message.channel.id in EARN_CHANNEL_IDS and not content.startswith("/"):
        try:
            await earn_for_message(message.author.id, datetime.now(tz=TZ), len(content), message.guild, message.author.id)
        except Exception as e:
            print(f"[earn] {e}")

    # Cross-trade detector
    if message.channel.id != MOD_LOG_CHANNEL_ID and ((not MONITORED_CHANNEL_IDS) or (message.channel.id in MONITORED_CHANNEL_IDS)):
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
                # throttle per-user
                nowt = time(); key = f"report_cool:{message.author.id}"
                last = float(await db_get_meta(key) or 0)
                if nowt - last >= 120:
                    await db_set_meta(key, str(nowt))
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
                        try: await modlog.send(embed=embed)
                        except Exception: pass

# ================== MEMBER JOIN ==================
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot or member.guild.id != GUILD_ID: return
    newcomer = member.guild.get_role(NEWCOMER_ROLE_ID)
    if newcomer:
        try: await member.add_roles(newcomer, reason="New member")
        except Exception: pass

# ================== RUN ==================
def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token: raise RuntimeError("DISCORD_TOKEN env var is missing")
    bot.run(token)

if __name__ == "__main__":
    main()