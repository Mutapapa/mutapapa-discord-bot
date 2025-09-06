# bot.py

import os
import asyncio
import json
import re
import hmac
import hashlib
import xml.etree.ElementTree as ET
from time import time
from datetime import datetime, timedelta, timezone

import aiohttp
from aiohttp import web
import discord
from discord.ext import tasks

# ================== YOUR IDs / CONFIG ==================
# Discord
GUILD_ID = 1411205177880608831
WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID = 1411957261009555536
MEMBER_ROLE_ID = 1411938410041708585
MOD_LOG_CHANNEL_ID = 1413297073348018299

# Channels to monitor (leave [] to monitor all)
MONITORED_CHANNEL_IDS = [
    1411930067994411139, 1411930091109224479, 1411930638260502638,
    1411930689460240395, 1411931034026643476
]

# YouTube (WebSub push)
YT_CHANNEL_ID = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID = 1412989373556850829
YT_CALLBACK_PATH = "/yt/webhook"
YT_HUB = "https://pubsubhubbub.appspot.com"
YT_SECRET = "mutapapa-youtube"   # optional HMAC secret

# Hosted banner URL
BANNER_URL = "https://cdn.discordapp.com/attachments/1411930091109224479/1413654925602459769/Welcome_to_the_Mutapapa_Official_Discord_Server_Image.png?ex=68bcb83e&is=68bb66be&hm=f248257c26608d0ee69b8baab82f62aea768f15f090ad318617e68350fe3b5ac&"
# ========================================================

# ===== age-gate config persistence =====
CONFIG_FILE = "config.json"

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # defaults: ON, 7 days
        return {"age_gate_enabled": True, "min_account_age_sec": 7 * 24 * 3600}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

CONFIG = load_config()

# parse "10d" / "24h" / "30m"
def parse_duration_to_seconds(s: str):
    s = s.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([dhm])", s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        return n * 24 * 3600
    if unit == "h":
        return n * 3600
    if unit == "m":
        return n * 60
    return None

def humanize_seconds(sec: int) -> str:
    if sec % (24*3600) == 0:
        return f"{sec // (24*3600)}d"
    if sec % 3600 == 0:
        return f"{sec // 3600}h"
    if sec % 60 == 0:
        return f"{sec // 60}m"
    return f"{sec}s"

DATA_FILE = "join_times.json"

# -------- persistence for probation timers (ephemeral on free plans) --------
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

join_times = load_data()

# -------- client --------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# -------- text normalization --------
LEET_MAP = str.maketrans({"$": "s", "@": "a", "0": "o", "1": "i", "3": "e", "5": "s", "7": "t"})

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

# ================== YouTube webhook ==================
app = web.Application()

async def yt_webhook_handler(request: web.Request):
    if request.method == "GET":
        return web.Response(text=request.query.get("hub.challenge") or "ok")

    body = await request.read()

    # Verify HMAC if secret set
    if YT_SECRET:
        sig = request.headers.get("X-Hub-Signature", "")
        try:
            alg, hexdigest = sig.split("=", 1)
            digestmod = {"sha1": hashlib.sha1,"sha256": hashlib.sha256}.get(alg.lower())
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

# Single routes block
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

# ================== Discord events & commands ==================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} | latency={bot.latency:.3f}s")
    asyncio.create_task(start_webserver())
    public_url = os.getenv("PUBLIC_BASE_URL","").rstrip("/")
    if public_url:
        asyncio.create_task(websub_subscribe(public_url))
    else:
        print("[yt-webhook] PUBLIC_BASE_URL not set; skipping subscription.")
    promote_loop.start()

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content.strip().lower()

    # simple ping
    if content == "!ping":
        await message.channel.send("pong 🏓")
        return

    # admin: show min age
    if content == "!showminage":
        await message.channel.send(
            f"Age-gate is **{'ON' if CONFIG.get('age_gate_enabled', True) else 'OFF'}**, "
            f"min age = **{humanize_seconds(CONFIG.get('min_account_age_sec', 7*24*3600))}**."
        )
        return

    # admin: toggle age gate
    if content.startswith("!agegate "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        arg = content.split(maxsplit=1)[1]
        if arg in ("on", "off"):
            CONFIG["age_gate_enabled"] = (arg == "on")
            save_config(CONFIG)
            await message.channel.send(f"✅ Age-gate turned **{arg.upper()}**.")
        else:
            await message.channel.send("Usage: `!agegate on` or `!agegate off`")
        return

    # admin: set min age
    if content.startswith("!setminage"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        parts = message.content.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `!setminage <number>d|h|m`  e.g. `!setminage 10d`")
            return
        sec = parse_duration_to_seconds(parts[1])
        if sec is None or sec <= 0:
            await message.channel.send("❗ Invalid. Use like `!setminage 7d` or `!setminage 24h`.")
            return
        CONFIG["min_account_age_sec"] = int(sec)
        save_config(CONFIG)
        await message.channel.send(f"✅ Minimum account age set to **{humanize_seconds(sec)}**.")
        return

    # test mod-log
    if content == "!modlogtest":
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
        return

    # skip logging the mod-log channel itself
    if message.channel.id == MOD_LOG_CHANNEL_ID:
        return
    # only monitored channels (if list not empty)
    if MONITORED_CHANNEL_IDS and (message.channel.id not in MONITORED_CHANNEL_IDS):
        return

    raw = message.content or ""
    if not raw.strip():
        return
    norm = normalize_text(raw)

    hits = set()
    for w in BUY_SELL_WORDS:
        if f" {w} " in f" {norm} ":
            hits.add(w)
    for w in CROSSTRADE_HINTS:
        if f" {w} " in f" {norm} ":
            hits.add(w)
    for rx in CROSSTRADE_PATTERNS:
        if rx.search(raw) or rx.search(norm):
            hits.add(rx.pattern)

    if not hits:
        return

    now = time()
    last = _last_report_by_user.get(message.author.id, 0)
    if now - last < _report_cooldown_sec:
        return
    _last_report_by_user[message.author.id] = now

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
        print(f"[modlog] Reported {message.author} in #{message.channel} with hits: {hits}")

@bot.event
async def on_member_join(member: discord.Member):
    # ignore bots; enforce only in your guild
    if member.bot or member.guild.id != GUILD_ID:
        return

    guild = member.guild
    now = datetime.now(timezone.utc)

    # ---- Account age gate (configurable & persisted) ----
    if CONFIG.get("age_gate_enabled", True):
        acct_age_sec = (now - member.created_at).total_seconds()
        min_sec = int(CONFIG.get("min_account_age_sec", 7*24*3600))
        if acct_age_sec <= min_sec:
            # Try to DM first (may fail if DMs are closed)
            try:
                dm = await member.create_dm()
                await dm.send(
                    "You have been kicked from the **Mutapapa Official Discord Server**.\n"
                    "Reason: Your Discord account **must** be older than 7 days to join."
                )
            except Exception:
                pass  # fine if we can't DM

            # Kick the user
            try:
                await member.kick(reason=f"Account younger than {humanize_seconds(min_sec)} (auto-moderation)")
            except discord.Forbidden:
                print("❗ Failed to kick: missing permission or role order.")

            # Log to mod-log if available
            modlog = guild.get_channel(MOD_LOG_CHANNEL_ID)
            if modlog:
                em = discord.Embed(
                    title="👟 Auto-kick: New Account",
                    description=(
                        f"**User:** {member} (`{member.id}`)\n"
                        f"**Account created:** {member.created_at:%Y-%m-%d %H:%M UTC}\n"
                        f"**Age:** ~{int(acct_age_sec//86400)} day(s)\n"
                        f"**Reason:** Account younger than {humanize_seconds(min_sec)}"
                    ),
                    color=0xE67E22
                )
                em.timestamp = discord.utils.utcnow()
                await modlog.send(embed=em)

            # ensure we don't track probation for kicked users
            store = join_times.get(str(GUILD_ID), {})
            store.pop(str(member.id), None)
            join_times[str(GUILD_ID)] = store
            save_data(join_times)
            return  # stop: do not welcome / assign roles

    # ---- Normal path for allowed accounts ----
    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    if newcomer:
        try:
            await member.add_roles(newcomer, reason="New member")
        except discord.Forbidden:
            print("❗ Cannot assign @Newcomer (check role order/permissions).")

    # Save probation start
    gstore = join_times.setdefault(str(GUILD_ID), {})
    gstore[str(member.id)] = now.isoformat()
    save_data(join_times)

    # Welcome embed
    channel = guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title=f"Welcome to {guild.name}, {member.name}!",
            description=(f"Hey {member.mention}! Welcome to the **Mutapapa Official Discord Server!** "
                         "We hope you have a great time here!"),
            color=0x0089FF
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url=BANNER_URL)
        await channel.send(embed=embed)

# promote Newcomer -> Member after 3 days
@tasks.loop(minutes=5)
async def promote_loop():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    member_role = guild.get_role(MEMBER_ROLE_ID)
    if not newcomer or not member_role:
        return
    store = join_times.get(str(GUILD_ID), {})
    now = datetime.now(timezone.utc)
    processed = []
    for uid, iso in list(store.items()):
        try:
            joined_at = datetime.fromisoformat(iso)
        except Exception:
            processed.append(uid)
            continue
        if now - joined_at >= timedelta(days=3):
            m = guild.get_member(int(uid))
            if m:
                try:
                    if newcomer in m.roles:
                        await m.remove_roles(newcomer, reason="Probation ended")
                    if member_role not in m.roles:
                        await m.add_roles(member_role, reason="Auto promotion after 3 days")
                    print(f"✅ Promoted {m} to Member")
                except discord.Forbidden:
                    print("❗ Promotion failed")
            processed.append(uid)
    for uid in processed:
        store.pop(uid, None)
    if processed:
        join_times[str(GUILD_ID)] = store
        save_data(join_times)

# ----------------- run bot -----------------
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN env var is missing")
bot.run(token)