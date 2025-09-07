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

# ===== Counting channel (Asimo Says) =====
COUNT_CHANNEL_ID = 1414051875329802320  # <--- replace with the channel ID for #asimo-says-count-to-67
COUNT_STATE_FILE = "count_state.json"


# ================== REACTION ROLES ==================
REACTION_CHANNEL_ID = 1414001588091093052

REACTION_ROLE_MAP = {
    "📺": 1412989373556850829,
    "🔔": 1412993171670958232,
    "✖️": 1414001344297172992,
    "🎉": 1412992931148595301,
}

RR_STORE_FILE = "reaction_msg.json"
def load_rr_store():
    try:
        with open(RR_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
def save_rr_store(d):
    with open(RR_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)

# ===== Giveaways =====
GIVEAWAYS_FILE = "giveaways.json"  # persistent state

# ================== YOUR IDs / CONFIG ==================
GUILD_ID = 1411205177880608831
WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID = 1411957261009555536
MEMBER_ROLE_ID = 1411938410041708585
MOD_LOG_CHANNEL_ID = 1413297073348018299

# Win/Fair/Loss voting channel (ONLY reacts here)
WFL_CHANNEL_ID = 1411931034026643476

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
YT_SECRET = "mutapapa-youtube"

# X (Twitter) RSS
X_USERNAME = "Real_Mutapapa"
X_RSS_URL = os.getenv("X_RSS_URL", f"https://nitter.net/{X_USERNAME}/rss")
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_CACHE_FILE = "x_last_item.json"
def load_x_cache():
    try:
        with open(X_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
def save_x_cache(d):
    with open(X_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)
def nitter_to_x(url: str) -> str:
    return url.replace("https://nitter.net", "https://x.com")

BANNER_URL = "https://cdn.discordapp.com/attachments/1411930091109224479/1413654925602459769/Welcome_to_the_Mutapapa_Official_Discord_Server_Image.png?ex=68bcb83e&is=68bb66be&hm=f248257c26608d0ee69b8baab82f62aea768f15f090ad318617e68350fe3b5ac&"
def load_giveaways():
    try:
        with open(GIVEAWAYS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # message_id (str) -> dict{channel_id,int, ends_at, winners, title, desc, participants:[int], ended:bool}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_giveaways(d):
    with open(GIVEAWAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)

GIVEAWAYS = load_giveaways()

# ===== age-gate config =====
CONFIG_FILE = "config.json"
def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"age_gate_enabled": True, "min_account_age_sec": 7 * 24 * 3600}
def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
CONFIG = load_config()

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

# ===== probation timers =====
DATA_FILE = "join_times.json"
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

# ===== client =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# ===== cross-trade detector =====
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

def load_count_state():
    try:
        with open(COUNT_STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError
            # defaults
            d.setdefault("expected_next", 1)
            d.setdefault("goal", 67)
            return d
    except Exception:
        return {"expected_next": 1, "goal": 67}

def save_count_state(d: dict):
    with open(COUNT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)

COUNT_STATE = load_count_state()


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
    if YT_SECRET: data["hub.secret"] = YT_SECRET
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{YT_HUB}/subscribe", data=data, timeout=10) as resp:
                print(f"[yt-webhook] subscribe {resp.status} -> {callback}")
    except Exception as e:
        print(f"[yt-webhook] subscribe error: {e}")

from discord.ui import View, button
import random

class GiveawayView(View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)  # persistent until ended
        self.message_id = message_id

    @button(label="Enter", style=discord.ButtonStyle.primary, emoji="🎉", custom_id="gw_enter")
    async def enter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
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
    async def view_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        mid = str(self.message_id)
        gw = GIVEAWAYS.get(mid)
        if not gw:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)

        parts = gw.get("participants", [])
        if not parts:
            return await interaction.response.send_message("No participants yet.", ephemeral=True)

        # Show as mentions in chunks to avoid hitting limits
        mentions = [f"<@{uid}>" for uid in parts][:100]  # keep it short
        txt = "Participants (" + str(len(parts)) + "):\n" + ", ".join(mentions)
        await interaction.response.send_message(txt, ephemeral=True)

async def schedule_giveaway_end(message_id: int, ends_at_unix: float):
    # re-schedules after restarts
    delay = max(0, ends_at_unix - asyncio.get_event_loop().time() + (asyncio.get_event_loop().time() - time()))
    # simpler: sleep until wall time
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

    # pick winners
    parts = [p for p in set(gw.get("participants", [])) if isinstance(p, int)]
    winners_count = max(1, int(gw.get("winners", 1)))
    if len(parts) == 0:
        winners = []
    else:
        winners = random.sample(parts, k=min(winners_count, len(parts)))

    # edit embed
    embed = discord.Embed(title=gw.get("title") or "Giveaway", description=gw.get("desc") or "", color=0x5865F2)
    embed.add_field(name="Winners", value=("None" if not winners else " ".join(f"<@{w}>" for w in winners)))
    embed.set_footer(text="Giveaway ended")
    view = GiveawayView(message_id)
    for item in view.children:
        item.disabled = True

    if msg:
        try:
            await msg.edit(embed=embed, view=view)
        except Exception:
            pass

    # announce in channel
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
    x_posts_loop.start()

@bot.event
async def on_ready():
    # reattach views for active giveaways
    for mid, gw in list(GIVEAWAYS.items()):
        if not gw.get("ended") and gw.get("channel_id"):
            bot.add_view(GiveawayView(int(mid)))
            # re-schedule end if ends_at exists
            ends_at = gw.get("ends_at")
            if ends_at:
                asyncio.create_task(schedule_giveaway_end(int(mid), ends_at))

    print(f"Logged in as {bot.user} | latency={bot.latency:.3f}s")
    # ... your existing on_ready code (start webserver, loops, etc.)


@bot.event
async def on_message(message: discord.Message):

    # ===== GIVEAWAY COMMANDS =====
    if clower.startswith("!gstart "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        # format: !gstart <duration> | <winners> | <title> | <description>
        try:
            _, rest = message.content.split(" ", 1)
            parts = [p.strip() for p in rest.split("|")]
            dur_s = parse_duration_to_seconds(parts[0])            # e.g. 1h, 30m, 2d
            winners_count = int(parts[1])
            title = parts[2]
            desc = parts[3] if len(parts) > 3 else ""
        except Exception:
            return await message.channel.send(
                "Usage: `!gstart <duration> | <winners> | <title> | <description>`\n"
                "e.g. `!gstart 2h | 2 | Nitro Classic | Click Enter to join!`"
            )

        if not dur_s or dur_s <= 0 or winners_count < 1:
            return await message.channel.send("❗ Bad duration or winners.")

        ends_at = time() + dur_s
        embed = discord.Embed(title=title, description=desc, color=0x5865F2)
        embed.add_field(name="Duration", value=f"{parts[0]}")
        embed.add_field(name="Winners", value=str(winners_count))
        embed.set_footer(text="Press Enter to join • View Participants to see who’s in")

        sent = await message.channel.send(embed=embed, view=GiveawayView(0))  # temp view, fix id right after
        # Save state
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

        # reattach view with correct message id (so custom_id grouping is stable)
        view = GiveawayView(sent.id)
        try:
            await sent.edit(view=view)
        except Exception:
            pass

        # schedule the ending
        asyncio.create_task(schedule_giveaway_end(sent.id, ends_at))

        return

    if clower.startswith("!gend"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        # !gend <message_id>
        try:
            mid = message.content.split(maxsplit=1)[1].strip()
            _ = int(mid)
        except Exception:
            return await message.channel.send("Usage: `!gend <message_id>`")

        await end_giveaway(int(mid))
        await message.channel.send("✅ Ended (or already ended).")
        return

    if clower.startswith("!greroll"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        # !greroll <message_id>
        try:
            mid = message.content.split(maxsplit=1)[1].strip()
            _ = int(mid)
        except Exception:
            return await message.channel.send("Usage: `!greroll <message_id>`")

        # mark not ended temporarily and call end again to pick new winners
        gw = GIVEAWAYS.get(mid)
        if not gw:
            return await message.channel.send("Not found.")
        gw["ended"] = False
        save_giveaways(GIVEAWAYS)
        await end_giveaway(int(mid))
        await message.channel.send("✅ Rerolled.")
        return


    # ---------- COUNTING CHANNEL RULES ----------
    if message.channel.id == COUNT_CHANNEL_ID and not message.author.bot:
        # allow admin commands in this channel (so you can adjust goal/next)
        if message.content.startswith("!"):
            pass  # let commands below handle it
        else:
            txt = message.content.strip()

            # must be digits only (no spaces, punctuation, emojis, etc.)
            if not re.fullmatch(r"\d+", txt):
                try:
                    await message.delete()
                except Exception:
                    pass
                return

            n = int(txt)
            expected = COUNT_STATE.get("expected_next", 1)
            goal = COUNT_STATE.get("goal", 67)

            # wrong number -> delete silently
            if n != expected:
                try:
                    await message.delete()
                except Exception:
                    pass
                return

            # correct -> advance counter
            COUNT_STATE["expected_next"] = expected + 1
            save_count_state(COUNT_STATE)

            # optional: if you want to stop exactly at goal, delete any numbers > goal
            # and (optionally) post a completion message. By default we just keep going.

    if message.author.bot or not message.guild:
        return

    content = message.content.strip()
    clower = content.lower()

    # ----- COUNT ADMIN COMMANDS -----
    if clower.startswith("!countgoal "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        try:
            new_goal = int(message.content.split(maxsplit=1)[1])
            if new_goal < 1:
                raise ValueError
        except Exception:
            await message.channel.send("Usage: `!countgoal <positive integer>`")
            return
        COUNT_STATE["goal"] = new_goal
        save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Goal set to **{new_goal}**.")

        return

    if clower.startswith("!countnext "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        try:
            new_next = int(message.content.split(maxsplit=1)[1])
            if new_next < 1:
                raise ValueError
        except Exception:
            await message.channel.send("Usage: `!countnext <positive integer>`")
            return
        COUNT_STATE["expected_next"] = new_next
        save_count_state(COUNT_STATE)
        await message.channel.send(f"✅ Next expected number set to **{new_next}**.")
        return

    if clower == "!countreset":
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        COUNT_STATE["expected_next"] = 1
        save_count_state(COUNT_STATE)
        await message.channel.send("✅ Counter reset. Next expected number is **1**.")
        return

    if clower == "!countstatus":
        st = COUNT_STATE
        await message.channel.send(
            f"🔢 Next: **{st.get('expected_next', 1)}** | Goal: **{st.get('goal', 67)}**"
        )
        return


    # simple ping
    if clower == "!ping":
        await message.channel.send("pong 🏓")
        return

    # send as bot
    if clower.startswith("!send "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        text = content.split(" ", 1)[1].strip()
        if not text:
            await message.channel.send("Usage: `!send <message>`")
            return
        await message.channel.send(text)
        return

    # create reaction-role message
    if clower.startswith("!sendreact "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        rr_channel = message.guild.get_channel(REACTION_CHANNEL_ID)
        if not rr_channel:
            await message.channel.send("❗ REACTION_CHANNEL_ID is wrong or I can’t see that channel.")
            return
        body = content.split(" ", 1)[1].strip()
        if not body:
            await message.channel.send("Usage: `!sendreact <message to show users>`")
            return
        sent = await rr_channel.send(body)
        for emoji in REACTION_ROLE_MAP.keys():
            try:
                await sent.add_reaction(emoji)
            except Exception:
                pass
        store = load_rr_store()
        store["message_id"] = sent.id
        store["channel_id"] = rr_channel.id
        save_rr_store(store)
        await message.channel.send(f"✅ Reaction-roles set on message ID `{sent.id}` in {rr_channel.mention}.")
        return

    # age-gate helpers
    if clower == "!showminage":
        await message.channel.send(
            f"Age-gate is **{'ON' if CONFIG.get('age_gate_enabled', True) else 'OFF'}**, "
            f"min age = **{humanize_seconds(CONFIG.get('min_account_age_sec', 7*24*3600))}**."
        )
        return

    if clower.startswith("!agegate "):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        arg = clower.split(maxsplit=1)[1]
        if arg in ("on", "off"):
            CONFIG["age_gate_enabled"] = (arg == "on")
            save_config(CONFIG)
            await message.channel.send(f"✅ Age-gate turned **{arg.upper()}**.")
        else:
            await message.channel.send("Usage: `!agegate on` or `!agegate off`")
        return

    if clower.startswith("!setminage"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❗ Admins only.")
            return
        parts = content.split(maxsplit=1)
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
        return

    # ---------- W/F/L auto-reaction (ONLY in WFL_CHANNEL_ID) ----------
    if message.channel.id == WFL_CHANNEL_ID:
        t = message.content.lower()
        has_wfl = (
            re.search(r"\bw\s*/\s*f\s*/\s*l\b", t) or                 # w/f/l
            re.search(r"\bwin\b.*\bfair\b.*\bloss\b", t) or           # win ... fair ... loss
            re.search(r"\bw\s+f\s+l\b", t) or                         # w f l
            re.search(r"\bwfl\b", t) or                               # wfl
            re.search(r"\bwin\s*[- ]\s*fair\s*[- ]\s*loss\b", t)      # win - fair - loss
        )
        if has_wfl:
            try:
                await message.add_reaction("🇼")
                await message.add_reaction("🇫")
                await message.add_reaction("🇱")
            except Exception as e:
                print(f"[wfl] failed to add reactions: {e}")
        # don't return; let the cross-trade detector run too if applicable

    # --- cross-trade detector ---
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
        print(f"[modlog] Reported {message.author} in #{message.channel} with hits: {hits}")

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
    if not guild:
        return
    role = guild.get_role(role_id)
    if not role:
        return
    member = guild.get_member(payload.user_id)
    if not member:
        return
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
    if not guild:
        return
    role = guild.get_role(role_id)
    if not role:
        return
    member = guild.get_member(payload.user_id)
    if not member:
        return
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Reaction role remove")
    except discord.Forbidden:
        print("❗ Missing permission to remove role — move bot role above target role.")
    except Exception as e:
        print(f"[rr] remove error: {e}")

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

# ===== Background loops =====
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

@tasks.loop(minutes=2)
async def x_posts_loop():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(X_ANNOUNCE_CHANNEL_ID)
    if not ch:
        return
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
        link = (it.findtext("link") or "").strip()
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
        print(f"[x] announced {len(new_items)} new post(s)")

# ----------------- run bot -----------------
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN env var is missing")
bot.run(token)