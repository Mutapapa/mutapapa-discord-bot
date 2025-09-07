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
import random

import aiohttp
from aiohttp import web
import discord
from discord.ext import tasks
from discord.ui import View, button

# ================== REQUIRED ENV ==================
# DISCORD_TOKEN
# PUBLIC_BASE_URL
# X_RSS_URL (optional)
# ==================================================

# ================== IDs / CONFIG ==================
GUILD_ID = 1411205177880608831
WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID   = 1411957261009555536
MEMBER_ROLE_ID     = 1411938410041708585
MOD_LOG_CHANNEL_ID = 1413297073348018299

WFL_CHANNEL_ID = 1411931034026643476

MONITORED_CHANNEL_IDS = [
    1411930067994411139, 1411930091109224479,
    1411930638260502638, 1411930689460240395,
    1411931034026643476
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

# Counting channel
COUNT_CHANNEL_ID  = 1414051875329802320
COUNT_STATE_FILE  = "count_state.json"  # {"expected_next": int, "goal": int}

# YouTube (WebSub)
YT_CHANNEL_ID          = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID        = 1412989373556850829
YT_CALLBACK_PATH       = "/yt/webhook"
YT_HUB                 = "https://pubsubhubbub.appspot.com"
YT_SECRET              = "mutapapa-youtube"

# X (Twitter) via RSS/Nitter
X_USERNAME              = "Real_Mutapapa"
X_RSS_URL               = os.getenv("X_RSS_URL", f"https://nitter.net/{X_USERNAME}/rss")
X_ANNOUNCE_CHANNEL_ID   = 1414000975680897128
X_CACHE_FILE            = "x_last_item.json"

# Welcome banner
BANNER_URL = "https://cdn.discordapp.com/attachments/1411930091109224479/1413654925602459769/Welcome_to_the_Mutapapa_Official_Discord_Server_Image.png?ex=68bcb83e&is=68bb66be&hm=f248257c26608d0ee69b8baab82f62aea768f15f090ad318617e68350fe3b5ac&"

# Giveaways
GIVEAWAYS_FILE = "giveaways.json"  # message_id -> { ... }

# Age gate
CONFIG_FILE = "config.json"  # {"age_gate_enabled": bool, "min_account_age_sec": int}

# Probation storage
DATA_FILE = "join_times.json"  # {guild_id: {user_id: iso}}

# ================== small JSON helpers ==================
def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = json.load(f)
            return v if isinstance(v, type(default)) or default is None else default
    except Exception:
        return default

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def load_rr_store(): return _load_json(RR_STORE_FILE, {})
def save_rr_store(d): _save_json(RR_STORE_FILE, d)

def load_x_cache(): return _load_json(X_CACHE_FILE, {})
def save_x_cache(d): _save_json(X_CACHE_FILE, d)

def load_giveaways(): return _load_json(GIVEAWAYS_FILE, {})
def save_giveaways(d): _save_json(GIVEAWAYS_FILE, d)

def load_config(): return _load_json(CONFIG_FILE, {"age_gate_enabled": True, "min_account_age_sec": 7 * 24 * 3600})
def save_config(cfg): _save_json(CONFIG_FILE, cfg)

def load_data(): return _load_json(DATA_FILE, {})
def save_data(data): _save_json(DATA_FILE, data)

def load_count_state():
    d = _load_json(COUNT_STATE_FILE, {"expected_next": 1, "goal": 67})
    d.setdefault("expected_next", 1)
    d.setdefault("goal", 67)
    return d
def save_count_state(d): _save_json(COUNT_STATE_FILE, d)

GIVEAWAYS  = load_giveaways()
CONFIG     = load_config()
join_times = load_data()
COUNT_STATE = load_count_state()

# ================== utils ==================
def parse_single_duration(tok: str):
    m = re.fullmatch(r"(\d+)\s*([dhms])", tok)
    if not m: return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "d": return n * 24 * 3600
    if unit == "h": return n * 3600
    if unit == "m": return n * 60
    if unit == "s": return n
    return None

def parse_compound_duration(s: str):
    """
    Accepts '1h', '30m', '90s', or compound like '1h 30m', '0h 1m'.
    Returns seconds or None if invalid.
    """
    s = s.strip().lower()
    if not s:
        return None
    total = 0
    for tok in s.split():
        val = parse_single_duration(tok)
        if val is None:
            return None
        total += val
    return total

def humanize_seconds(sec: int) -> str:
    if sec % (24*3600) == 0: return f"{sec // (24*3600)}d"
    if sec % 3600 == 0:      return f"{sec // 3600}h"
    if sec % 60 == 0:        return f"{sec // 60}m"
    return f"{sec}s"

def nitter_to_x(url: str) -> str:
    return url.replace("https://nitter.net", "https://x.com")

async def delete_cmd(msg: discord.Message):
    try: await msg.delete()
    except: pass

# ================== client / intents ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# ================== cross-trade detector ==================
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

# ================== YouTube webhook ==================
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
        vid   = entry.findtext("yt:videoId", default="", namespaces=ns)
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

async def health(_): return web.Response(text="ok")

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

# ================== Giveaways ==================
# state: GIVEAWAYS[msg_id_str] = {
#   channel_id, ends_at, winners, title, desc, participants:[user_id], ended:bool
# }

class GiveawayView(View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @button(label="Enter", style=discord.ButtonStyle.primary, emoji="🎉", custom_id="gw_enter")
    async def enter_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        mid = str(self.message_id)
        gw = GIVEAWAYS.get(mid)
        if not gw or gw.get("ended"):
            return await interaction.response.send_message("This giveaway is closed.", ephemeral=True)
        if interaction.user.bot:
            return await interaction.response.send_message("Bots can’t enter.", ephemeral=True)

        parts = set(gw.get("participants", []))
        if interaction.user.id in parts:
            return await interaction.response.send_message("You’re already in 🎉", ephemeral=True)

        parts.add(interaction.user.id)
        gw["participants"] = list(parts)
        GIVEAWAYS[mid] = gw
        save_giveaways(GIVEAWAYS)
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
    msg = None
    if channel:
        try:
            msg = await channel.fetch_message(message_id)
        except Exception:
            msg = None

    parts = [p for p in set(gw.get("participants", [])) if isinstance(p, int)]
    winners_count = max(1, int(gw.get("winners", 1)))
    winners = random.sample(parts, k=min(winners_count, len(parts))) if parts else []

    embed = discord.Embed(
        title=gw.get("title") or "Giveaway",
        description=gw.get("desc") or "",
        color=0x5865F2
    )
    win_text = "None" if not winners else " ".join(f"<@{w}>" for w in winners)
    embed.add_field(name="Winners", value=win_text)
    embed.set_footer(text="Giveaway ended")

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
                await channel.send("🎉 **Winners:** " + " ".join(f"<@{w}>" for w in winners))
            else:
                await channel.send("No valid entries.")
        except Exception:
            pass

    gw["ended"] = True
    GIVEAWAYS[mid] = gw
    save_giveaways(GIVEAWAYS)

def most_recent_active_giveaway_id() -> int | None:
    active = [(int(mid), data) for mid, data in GIVEAWAYS.items() if not data.get("ended")]
    if not active:
        return None
    active.sort(key=lambda x: x[1].get("ends_at", 0), reverse=True)
    return active[0][0]

# ================== Events ==================
@bot.event
async def on_ready():
    for mid, gw in list(GIVEAWAYS.items()):
        mid_int = int(mid)
        if not gw.get("ended") and gw.get("channel_id"):
            bot.add_view(GiveawayView(mid_int))
            if gw.get("ends_at"):
                asyncio.create_task(schedule_giveaway_end(mid_int, gw["ends_at"]))

    print(f"Logged in as {bot.user} | latency={bot.latency:.3f}s")

    asyncio.create_task(start_webserver())
    public_url = os.getenv("PUBLIC_BASE_URL","").rstrip("/")
    if public_url:
        asyncio.create_task(websub_subscribe(public_url))
    else:
        print("[yt-webhook] PUBLIC_BASE_URL not set; skipping subscription.")

    promote_loop.start()
    x_posts_loop.start()

@bot.event
async def on_message(message: discord.Message):
    # Counting channel guard
    if message.guild and message.channel.id == COUNT_CHANNEL_ID and not message.author.bot:
        if message.content.startswith("!"):
            pass
        else:
            txt = message.content.strip()
            if not re.fullmatch(r"\d+", txt):
                try: await message.delete()
                except: pass
                return
            n = int(txt)
            expected = COUNT_STATE.get("expected_next", 1)
            if n != expected:
                try: await message.delete()
                except: pass
                return
            COUNT_STATE["expected_next"] = expected + 1
            save_count_state(COUNT_STATE)

    if message.author.bot or not message.guild:
        return

    content = message.content.strip()
    clower  = content.lower()

    # ---------- Giveaways ----------
    if clower.startswith("!gstart "):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        # Formats supported:
        #   !gstart 1h 30m | 2 | Title | Description
        #   !gstart 1m | 1 | Title
        try:
            _, rest = message.content.split(" ", 1)
            parts = [p.strip() for p in rest.split("|")]
            if len(parts) < 2:
                raise ValueError
            dur_s = parse_compound_duration(parts[0])   # <-- accepts "0h 1m", "1m", "1h 30m"
            winners_count = int(parts[1])
            title = parts[2] if len(parts) > 2 else "Giveaway"
            desc = parts[3] if len(parts) > 3 else ""
        except Exception:
            return await message.channel.send(
                "Usage: `!gstart <duration> | <winners> | <title> | <description>`\n"
                "Examples: `!gstart 1m | 1 | Nitro Drop`  or  `!gstart 1h 30m | 2 | Big Prize | Click Enter to join!`"
            )

        if not dur_s or dur_s <= 0 or winners_count < 1:
            return await message.channel.send("❗ Bad duration or winners.")

        ends_at = time() + dur_s
        embed = discord.Embed(title=title, description=desc, color=0x5865F2)
        embed.add_field(name="Duration", value=f"{parts[0]}")
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

        try: await sent.edit(view=GiveawayView(sent.id))
        except Exception:
            pass

        asyncio.create_task(schedule_giveaway_end(sent.id, ends_at))
        await delete_cmd(message)
        return

    if clower.startswith("!gend"):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        parts = message.content.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip().isdigit():
            target_id = int(parts[1].strip())
        else:
            target_id = most_recent_active_giveaway_id()
        if not target_id:
            return await message.channel.send("No active giveaway found.")
        await end_giveaway(target_id)
        await delete_cmd(message)
        return

    if clower.startswith("!greroll"):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        parts = message.content.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip().isdigit():
            target_id = int(parts[1].strip())
        else:
            if not GIVEAWAYS:
                return await message.channel.send("No giveaways found.")
            items = [(int(mid), d.get("ends_at", 0)) for mid, d in GIVEAWAYS.items()]
            items.sort(key=lambda t: t[1], reverse=True)
            target_id = items[0][0]
        mid = str(target_id)
        gw = GIVEAWAYS.get(mid)
        if not gw:
            return await message.channel.send("Not found.")
        gw["ended"] = False
        save_giveaways(GIVEAWAYS)
        await end_giveaway(target_id)
        await delete_cmd(message)
        return

    # ---------- Count admin ----------
    if clower.startswith("!countgoal "):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        try:
            new_goal = int(message.content.split(maxsplit=1)[1])
            if new_goal < 1: raise ValueError
        except Exception:
            return await message.channel.send("Usage: `!countgoal <positive integer>`")
        COUNT_STATE["goal"] = new_goal
        save_count_state(COUNT_STATE)
        await delete_cmd(message)
        return await message.channel.send(f"✅ Goal set to **{new_goal}**.")

    if clower.startswith("!countnext "):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        try:
            new_next = int(message.content.split(maxsplit=1)[1])
            if new_next < 1: raise ValueError
        except Exception:
            return await message.channel.send("Usage: `!countnext <positive integer>`")
        COUNT_STATE["expected_next"] = new_next
        save_count_state(COUNT_STATE)
        await delete_cmd(message)
        return await message.channel.send(f"✅ Next expected number set to **{new_next}**.")

    if clower == "!countreset":
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        COUNT_STATE["expected_next"] = 1
        save_count_state(COUNT_STATE)
        await delete_cmd(message)
        return await message.channel.send("✅ Counter reset. Next expected number is **1**.")

    if clower == "!countstatus":
        await delete_cmd(message)
        st = COUNT_STATE
        return await message.channel.send(
            f"🔢 Next: **{st.get('expected_next', 1)}** | Goal: **{st.get('goal', 67)}**"
        )

    # ---------- Misc/admin ----------
    if clower == "!ping":
        await delete_cmd(message)
        return await message.channel.send("pong 🏓")

    if clower.startswith("!send "):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        text = content.split(" ", 1)[1].strip()
        if not text:
            return await message.channel.send("Usage: `!send <message>`")
        await delete_cmd(message)
        return await message.channel.send(text)

    if clower.startswith("!sendreact "):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        rr_channel = message.guild.get_channel(REACTION_CHANNEL_ID)
        if not rr_channel:
            return await message.channel.send("❗ REACTION_CHANNEL_ID is wrong or I can’t see that channel.")
        body = content.split(" ", 1)[1].strip()
        if not body:
            return await message.channel.send("Usage: `!sendreact <message to show users>`")
        sent = await rr_channel.send(body)
        for emoji in REACTION_ROLE_MAP.keys():
            try: await sent.add_reaction(emoji)
            except Exception: pass
        store = load_rr_store()
        store["message_id"] = sent.id
        store["channel_id"] = rr_channel.id
        save_rr_store(store)
        await delete_cmd(message)
        return await message.channel.send(f"✅ Reaction-roles set on message ID `{sent.id}` in {rr_channel.mention}.")

    if clower == "!showminage":
        await delete_cmd(message)
        return await message.channel.send(
            f"Age-gate is **{'ON' if CONFIG.get('age_gate_enabled', True) else 'OFF'}**, "
            f"min age = **{humanize_seconds(CONFIG.get('min_account_age_sec', 7*24*3600))}**."
        )

    if clower.startswith("!agegate "):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        arg = clower.split(maxsplit=1)[1]
        if arg in ("on", "off"):
            CONFIG["age_gate_enabled"] = (arg == "on")
            save_config(CONFIG)
            await delete_cmd(message)
            return await message.channel.send(f"✅ Age-gate turned **{arg.upper()}**.")
        else:
            return await message.channel.send("Usage: `!agegate on` or `!agegate off`")

    if clower.startswith("!setminage"):
        if not message.author.guild_permissions.administrator:
            return await message.channel.send("❗ Admins only.")
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            return await message.channel.send("Usage: `!setminage <number>d|h|m`")
        # still supports single-token here (e.g., 7d). Keep simple.
        m = re.fullmatch(r"(\d+)\s*([dhm])", parts[1].strip().lower())
        if not m:
            return await message.channel.send("❗ Invalid. Example: `!setminage 7d` or `!setminage 24h`.")
        n = int(m.group(1)); u = m.group(2)
        sec = n*24*3600 if u=="d" else n*3600 if u=="h" else n*60
        CONFIG["min_account_age_sec"] = int(sec)
        save_config(CONFIG)
        await delete_cmd(message)
        return await message.channel.send(f"✅ Minimum account age set to **{humanize_seconds(sec)}**.")

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
            await delete_cmd(message)
            return await message.channel.send("✅ Sent a test embed to mod-log.")
        else:
            return await message.channel.send("❗ MOD_LOG_CHANNEL_ID wrong or I can’t see that channel.")

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
                print(f"[wfl] add reaction failed: {e}")

    # ---------- Cross-trade detector ----------
    if message.channel.id == MOD_LOG_CHANNEL_ID:
        return
    if MONITORED_CHANNEL_IDS and (message.channel.id not in MONITORED_CHANNEL_IDS):
        return
    raw = message.content or ""
    if not raw.strip():
        return
    norm = normalize_text(raw)
    hits = set()
    for w in BUY_SELL_WORDS:
        if f" {w} " in f" {norm} ": hits.add(w)
    for w in CROSSTRADE_HINTS:
        if f" {w} " in f" {norm} ": hits.add(w)
    for rx in CROSSTRADE_PATTERNS:
        if rx.search(raw) or rx.search(norm): hits.add(rx.pattern)
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

# ================== Reaction Roles add/remove ==================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    if payload.user_id == (bot.user.id if bot.user else 0):
        return
    store = load_rr_store()
    tracked_msg_id = store.get("message_id")
    tracked_chan_id = store.get("channel_id")
    if not tracked_msg_id or not tracked_chan_id:
        return
    if payload.message_id != tracked_msg_id or payload.channel_id != tracked_chan_id:
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
    except discord.Forbidden:
        print("❗ Missing permission to add role — move bot role above target role.")
    except Exception as e:
        print(f"[rr] add error: {e}")

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id != GUILD_ID:
        return
    store = load_rr_store()
    tracked_msg_id = store.get("message_id")
    tracked_chan_id = store.get("channel_id")
    if not tracked_msg_id or not tracked_chan_id:
        return
    if payload.message_id != tracked_msg_id or payload.channel_id != tracked_chan_id:
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
    except discord.Forbidden:
        print("❗ Missing permission to remove role — move bot role above target role.")
    except Exception as e:
        print(f"[rr] remove error: {e}")

# ================== Member join ==================
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot or member.guild.id != GUILD_ID:
        return
    guild = member.guild
    now = datetime.now(timezone.utc)

    if CONFIG.get("age_gate_enabled", True):
        acct_age_sec = (now - member.created_at).total_seconds()
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
            store = join_times.get(str(GUILD_ID), {})
            store.pop(str(member.id), None)
            join_times[str(GUILD_ID)] = store
            save_data(join_times)
            return

    newcomer = guild.get_role(NEWCOMER_ROLE_ID)
    if newcomer:
        try:
            await member.add_roles(newcomer, reason="New member")
        except discord.Forbidden:
            print("❗ Cannot assign @Newcomer (check role order/permissions).")

    gstore = join_times.setdefault(str(GUILD_ID), {})
    gstore[str(member.id)] = now.isoformat()
    save_data(join_times)

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

# ================== Background loops ==================
@tasks.loop(minutes=5)
async def promote_loop():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    newcomer    = guild.get_role(NEWCOMER_ROLE_ID)
    member_role = guild.get_role(MEMBER_ROLE_ID)
    if not newcomer or not member_role: return
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
                except discord.Forbidden:
                    print("❗ Promotion failed")
            processed.append(uid)
    for uid in processed:
        store.pop(uid, None)
    if processed:
        join_times[str(GUILD_ID)] = store
        save_data(join_times)

@tasks.loop(minutes=2)
async def x_posts_loop():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    if not ch: return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(X_RSS_URL, timeout=12) as resp:
                if resp.status != 200:
                    print(f"[x] rss status {resp.status}")
                    return
                xml = await resp.text()
    except Exception as e:
        print(f"[x] fetch error: {e}")
        return
    try:
        root = ET.fromstring(xml)
        channel = root.find("./channel")
        items = channel.findall("item") if channel is not None else []
        if not items:
            return
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
        await ch.send(embed=embed)
        guid = (it.findtext("guid") or it.findtext("link") or "").strip()
        if guid:
            latest_guid = guid
    if latest_guid and latest_guid != last_guid:
        save_x_cache({"last_guid": latest_guid})

# ================== Run ==================
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN env var is missing")
bot.run(token)