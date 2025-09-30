# bot.py
# Single-file Discord bot for the “Mutapapa Official” server

import os, re, json, random, asyncio, hmac, hashlib
from time import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import asyncpg
import aiohttp
from aiohttp import web
import discord
from discord.ext import commands, tasks
from discord.ui import View, button

# ================== CORE CONFIG ==================
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
TZ = ZoneInfo("America/Edmonton")
PORT = int(os.getenv("PORT", "10000"))  # Render-style
BANNER_URL = os.getenv("BANNER_URL", "")
X_RSS_URL = os.getenv("X_RSS_URL", "https://nitter.net/Real_Mutapapa/rss")
YT_WEBHOOK_SECRET = os.getenv("YT_WEBHOOK_SECRET", "mutapapa-youtube")

def utc_now() -> datetime: return datetime.now(timezone.utc)
def now_local() -> datetime: return datetime.now(TZ)

# ================== IDS (FINAL) ==================
GUILD_ID = 1411205177880608831
WELCOME_CHANNEL_ID = 1411946767414591538
NEWCOMER_ROLE_ID = 1411957261009555536
MEMBER_ROLE_ID = 1411938410041708585
MOD_LOG_CHANNEL_ID = 1413297073348018299
LEVEL_UP_ANNOUNCE_CHANNEL_ID = 1415505829401989131
REACTION_ROLE_CHANNEL_ID = 1414001588091093052
REACTION_ROLE_MAP = {"📺":1412989373556850829,"🔔":1412993171670958232,"✖️":1414001344297172992,"🎉":1412992931148595301}
WFL_CHANNEL_ID = 1411931034026643476
COUNT_CHANNEL_ID = 1414051875329802320
BUG_REVIEW_CHANNEL_ID = 1414124214956593242
PENALTY_APPROVALS_CHANNEL_ID = 1414124795418640535
CASH_DROP_CHANNEL_ID = 1414120740327788594
LEADERBOARD_CHANNEL_ID = 1414124214956593242
YT_ANNOUNCE_CHANNEL_ID = 1412144563144888452
YT_PING_ROLE_ID = 1412989373556850829
X_ANNOUNCE_CHANNEL_ID = 1414000975680897128
X_PING_ROLE_ID = 1414001344297172992
SEASON_ANNOUNCE_CHANNEL_IDS = [
    1414000088790863874, 1411931034026643476, 1411930067994411139,
    1411930091109224479, 1411930689460240395, 1414120740327788594
]

# Cross-trade excluded categories (no logging there)
CROSS_TRADE_EXCLUDED_CATEGORY_IDS = {
    1411935087867723826, 1411206110895149127, 1413998743682023515
}

# ================== ECONOMY CONFIG ==================
EARN_CHANNEL_IDS = [
    1411930638260502638,1411486271464935456,1413297073348018299,
    1411935203953217566,1411435784250331288,1412144563144888452,
    1411931216608755782,1414000975680897128,1411433941403177054,
    1411931171671117854,1411946767414591538,1413999346592256050,
    1414001588091093052
]
EARN_COOLDOWN_SEC = 180
EARN_PER_TICK = 200
DAILY_CAP = 2000
DOUBLE_CASH = False

# Random cash drops (scheduled 3–4/day)
DROP_AMOUNT = 225
DROP_WORD_COUNT = 4

# Bug rewards + monthly cap
BUG_REWARD_AMOUNT = 350
BUG_REWARD_LIMIT_PER_MONTH = 2

# Activity-based level roles
ROLE_ROOKIE = 1414817524557549629
ROLE_SQUAD = 1414818303028891731
ROLE_SPECIALIST = 1414818845541138493
ROLE_OPERATIVE = 1414819588448718880
ROLE_LEGEND = 1414819897602474057
ACTIVITY_THRESHOLDS = [
    (ROLE_ROOKIE,5000),(ROLE_SQUAD,25000),(ROLE_SPECIALIST,75000),
    (ROLE_OPERATIVE,180000),(ROLE_LEGEND,400000)
]

HELP_MOD_ROLE_IDS = {1413663966349234320,1411940485005578322,1413991410901713088}

# Counting channel state (also mirrored via commands)
COUNT_NEXT = 1
COUNT_GOAL = 67

# ================== DB INIT ==================
DB_URL = os.getenv("SUPABASE_DB_URL","").strip()
_pool: asyncpg.Pool | None = None

async def db_init():
    global _pool
    _pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=5)
    async with _pool.acquire() as con:
        await con.execute("""CREATE TABLE IF NOT EXISTS muta_meta(
            key TEXT PRIMARY KEY, value TEXT)""")
        await con.execute("""CREATE TABLE IF NOT EXISTS muta_users(
            user_id BIGINT PRIMARY KEY,
            cash BIGINT DEFAULT 0,
            last_earn_ts TIMESTAMPTZ,
            today_earned BIGINT DEFAULT 0,
            bug_rewards_this_month INT DEFAULT 0,
            activity_points BIGINT DEFAULT 0
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS muta_drops(
            id BIGSERIAL PRIMARY KEY,
            channel_id BIGINT,
            message_id BIGINT UNIQUE,
            phrase TEXT,
            amount INT,
            claimed_by BIGINT,
            claimed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""")
        await con.execute("""CREATE TABLE IF NOT EXISTS muta_giveaway_claims(
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT,
            giveaway_title TEXT,
            winner_id BIGINT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            answers JSONB DEFAULT '{}'::jsonb
        )""")

# Simple meta helpers
async def meta_get(key:str, default:str|None=None) -> str|None:
    row = await _pool.fetchrow("SELECT value FROM muta_meta WHERE key=$1", key)
    return row["value"] if row and row["value"] is not None else default

async def meta_set(key:str, value:str):
    await _pool.execute("""INSERT INTO muta_meta(key,value) VALUES($1,$2)
                           ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""", key, value)

# ================== DISCORD CLIENT ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

http: aiohttp.ClientSession | None = None
web_runner: web.AppRunner | None = None

# ================== ECONOMY & LEVELS ==================
async def ensure_user(uid:int):
    await _pool.execute("INSERT INTO muta_users(user_id) VALUES($1) ON CONFLICT DO NOTHING", uid)

async def add_cash(uid:int, amount:int) -> int:
    await ensure_user(uid)
    row = await _pool.fetchrow("UPDATE muta_users SET cash=cash+$1 WHERE user_id=$2 RETURNING cash", amount, uid)
    return int(row["cash"]) if row else 0

async def deduct_cash(uid:int, amount:int) -> int:
    await ensure_user(uid)
    row = await _pool.fetchrow("UPDATE muta_users SET cash=GREATEST(0,cash-$1) WHERE user_id=$2 RETURNING cash", amount, uid)
    return int(row["cash"]) if row else 0

async def leaderboard_top(n=10):
    return await _pool.fetch("SELECT user_id,cash FROM muta_users ORDER BY cash DESC LIMIT $1", n)

async def assign_activity_roles(member:discord.Member, points:int):
    granted=[]
    for rid, th in ACTIVITY_THRESHOLDS:
        if points>=th:
            role = member.guild.get_role(rid)
            if role and role not in member.roles:
                granted.append(role)
    if granted:
        await member.add_roles(*granted, reason="Activity level up")
        ch = member.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
        if ch: await ch.send(f"{member.mention} reached the **{granted[-1].name}** role! 🎉")

async def earn_for_message(uid:int, now:datetime, msg_len:int, guild:discord.Guild|None, author_id:int):
    await ensure_user(uid)
    row = await _pool.fetchrow("SELECT cash,last_earn_ts,today_earned,activity_points FROM muta_users WHERE user_id=$1", uid)
    last_ts=row["last_earn_ts"]; today=int(row["today_earned"] or 0); points=int(row["activity_points"] or 0)
    # daily rollover
    if last_ts and last_ts.astimezone(TZ).date()!=now.date(): today=0
    # cap & cooldown
    if today>=DAILY_CAP: return 0
    if last_ts and (now-last_ts).total_seconds()<EARN_COOLDOWN_SEC: return 0
    # length bonus
    bonus = 0 if msg_len<=9 else 50 if msg_len<=49 else 80 if msg_len<=99 else 100
    grant = min((EARN_PER_TICK+bonus)*(2 if DOUBLE_CASH else 1), DAILY_CAP-today)
    await _pool.execute("""UPDATE muta_users SET cash=cash+$1,last_earn_ts=$2,
                           today_earned=$3,activity_points=$4 WHERE user_id=$5""",
                        grant, now, today+grant, points+grant, uid)
    if guild:
        member = guild.get_member(author_id)
        if member: await assign_activity_roles(member, points+grant)
    return grant

# ================== GIVEAWAY CLAIMS ==================
class ClaimFormModal(discord.ui.Modal, title="Giveaway Claim"):
    def __init__(self,cog,claim_id:int):
        super().__init__(timeout=300); self.cog=cog; self.claim_id=claim_id
        self.roblox=discord.ui.TextInput(label="Roblox username",max_length=32,required=True)
        self.link=discord.ui.TextInput(label="Item link (optional)",required=False)
        self.extra=discord.ui.TextInput(label="Anything else",required=False,style=discord.TextStyle.paragraph)
        self.add_item(self.roblox); self.add_item(self.link); self.add_item(self.extra)
    async def on_submit(self,i:discord.Interaction):
        answers={"roblox":str(self.roblox.value).strip(),"item":str(self.link.value).strip(),"notes":str(self.extra.value).strip()}
        await self.cog._save_answers(self.claim_id,answers)
        await i.response.send_message("Thanks! Sent to Mutapapa 🎉", ephemeral=True)
        await self.cog._dm_admin_with_claim(self.claim_id,answers)

class ClaimStartView(discord.ui.View):
    def __init__(self,cog,claim_id:int): super().__init__(timeout=None); self.cog=cog; self.claim_id=claim_id
    @discord.ui.button(label="Open Claim Form",style=discord.ButtonStyle.primary)
    async def open_form(self,i:discord.Interaction,_): await i.response.send_modal(ClaimFormModal(self.cog,self.claim_id))

class GiveawayClaims(commands.Cog):
    def __init__(self,bot,pool): self.bot=bot; self.pool=pool; self._expiry.start()
    def cog_unload(self): self._expiry.cancel()
    async def start_claim_for_winner(self,guild,winner,title,announce,fallback):
        exp=(now_local()+timedelta(hours=24)).astimezone(timezone.utc)
        rec=await self.pool.fetchrow(
            "INSERT INTO muta_giveaway_claims(guild_id,giveaway_title,winner_id,expires_at) VALUES($1,$2,$3,$4) RETURNING id",
            guild.id,title,winner.id,exp)
        cid=rec["id"]
        try:
            await winner.send(
                f"Congrats {winner.mention}! You won **{title}** 🎉\nType `claim` or press button within 24h.",
                view=ClaimStartView(self,cid)
            )
        except discord.Forbidden:
            if announce: await announce.edit(content=announce.content+f"\n⚠️ <@{winner.id}> DM <@{ADMIN_USER_ID}> within 24h")
            elif fallback: await fallback.send(f"⚠️ <@{winner.id}> DM <@{ADMIN_USER_ID}> to claim **{title}**")
    @commands.Cog.listener("on_message")
    async def _listen(self,m:discord.Message):
        if m.guild or m.author.bot: return
        if "claim" not in m.content.lower(): return
        row=await self.pool.fetchrow(
            "SELECT id FROM muta_giveaway_claims WHERE winner_id=$1 AND status='pending' ORDER BY created_at DESC LIMIT 1",
            m.author.id)
        if row: await m.channel.send("Tap to claim.",view=ClaimStartView(self,row["id"]))
    async def _save_answers(self,cid:int,a:dict):
        await self.pool.execute("UPDATE muta_giveaway_claims SET answers=$2,status='submitted' WHERE id=$1",cid,json.dumps(a))
    async def _dm_admin_with_claim(self,cid:int,a:dict):
        admin=self.bot.get_user(ADMIN_USER_ID) or await self.bot.fetch_user(ADMIN_USER_ID)
        row=await self.pool.fetchrow("SELECT giveaway_title,winner_id FROM muta_giveaway_claims WHERE id=$1",cid)
        if not row: return
        try:
            await admin.send(
                f"**Claim {cid}**\nTitle: {row['giveaway_title']}\nWinner: <@{row['winner_id']}>\nRoblox: {a.get('roblox')}"
                f"\nItem: {a.get('item') or '—'}\nNotes: {a.get('notes') or '—'}\n\nReply `!paid {cid}` when done.")
        except: pass
    @commands.command(name="paid")
    async def mark_paid(self,ctx,cid:int):
        if ctx.author.id!=ADMIN_USER_ID and not ctx.author.guild_permissions.administrator: return
        row=await self.pool.fetchrow(
            "UPDATE muta_giveaway_claims SET status='paid' WHERE id=$1 AND status IN('pending','submitted') RETURNING winner_id,giveaway_title",cid)
        if not row: return await ctx.reply("No such claim.")
        try: (await self.bot.fetch_user(row["winner_id"])).send(
            f"Your giveaway **{row['giveaway_title']}** has been paid. DM <@{ADMIN_USER_ID}> if issues.")
        except: pass
        await ctx.reply(f"Claim {cid} marked paid.")
    @tasks.loop(minutes=10)
    async def _expiry(self):
        await self.pool.execute("UPDATE muta_giveaway_claims SET status='expired' WHERE status IN('pending','submitted') AND expires_at<NOW()")

async def setup_giveaway_claims(bot,pool):
    if not bot.get_cog("GiveawayClaims"): await bot.add_cog(GiveawayClaims(bot,pool))

# ================== GIVEAWAYS (Buttons) ==================
GIVEAWAYS: dict[str, dict] = {}

class GiveawayView(View):
    def __init__(self,message_id:int): super().__init__(timeout=None); self.message_id=message_id
    @button(label="Enter",style=discord.ButtonStyle.primary,emoji="🎉")
    async def enter(self,i:discord.Interaction,_):
        gw=GIVEAWAYS.get(str(self.message_id))
        if not gw or gw.get("ended"): return await i.response.send_message("Closed.",ephemeral=True)
        if i.user.id in gw.get("participants",[]): return await i.response.send_message("Already entered.",ephemeral=True)
        gw["participants"].append(i.user.id); GIVEAWAYS[str(self.message_id)]=gw
        await i.response.send_message("Entered! 🎉",ephemeral=True)
    @button(label="View Participants",style=discord.ButtonStyle.secondary,emoji="👀")
    async def view(self,i:discord.Interaction,_):
        gw=GIVEAWAYS.get(str(self.message_id))
        if not gw: return await i.response.send_message("Not found.",ephemeral=True)
        parts=gw.get("participants",[])
        await i.response.send_message(f"{len(parts)} participants:\n"+", ".join(f"<@{u}>" for u in parts),ephemeral=True)

async def schedule_giveaway_end(mid:int,ends:float):
    await asyncio.sleep(max(0, ends-time()))
    await end_giveaway(mid)

async def end_giveaway(mid:int):
    gw=GIVEAWAYS.get(str(mid))
    if not gw or gw.get("ended"): return
    ch=bot.get_channel(gw["channel_id"]); winners=[]
    if ch:
        try: msg=await ch.fetch_message(mid)
        except: msg=None
        parts=list(set(gw.get("participants",[]))); k=min(int(gw["winners"]),len(parts))
        winners=random.sample(parts,k=k) if parts else []
        embed=discord.Embed(title=f"🎉 {gw['title']} — ENDED",description=f"{gw['desc']}\n\n**Winners:** "+(" ".join(f"<@{w}>" for w in winners) if winners else "None"),color=0x5865F2)
        v=GiveawayView(mid); [setattr(b,"disabled",True) for b in v.children]
        if msg: await msg.edit(embed=embed,view=v)
        if winners:
            sent=await ch.send("🎉 Congrats "+" ".join(f"<@{w}>" for w in winners))
            claims=bot.get_cog("GiveawayClaims")
            if not claims:
                await setup_giveaway_claims(bot,_pool); claims=bot.get_cog("GiveawayClaims")
            for w in winners:
                u=ch.guild.get_member(w)
                if u: await claims.start_claim_for_winner(ch.guild,u,gw["title"],sent,ch)
        else:
            await ch.send("No entries.")
    gw["ended"]=True; GIVEAWAYS[str(mid)]=gw

# ================== BUG REPORTS & PENALTIES ==================
class PenaltyView(View):
    def __init__(self,target_id:int,amount:int):
        super().__init__(timeout=300); self.target_id=target_id; self.amount=amount
    @button(label="Yes (deduct)",style=discord.ButtonStyle.danger,emoji="⚠️")
    async def yes(self,i:discord.Interaction,_):
        if not i.user.guild_permissions.manage_messages:
            return await i.response.send_message("Mods only.",ephemeral=True)
        new_bal=await deduct_cash(self.target_id,self.amount)
        await i.response.edit_message(content=f"✅ Deducted {self.amount}. New balance: {new_bal}",view=None)
    @button(label="No",style=discord.ButtonStyle.secondary,emoji="❌")
    async def no(self,i:discord.Interaction,_):
        if not i.user.guild_permissions.manage_messages:
            return await i.response.send_message("Mods only.",ephemeral=True)
        await i.response.edit_message(content="❎ Deduction cancelled.",view=None)

class BugApproveView(View):
    def __init__(self,reporter_id:int,desc:str):
        super().__init__(timeout=600); self.reporter_id=reporter_id; self.desc=desc
    @button(label="Approve",style=discord.ButtonStyle.success,emoji="✅")
    async def approve(self,i:discord.Interaction,_):
        if not i.user.guild_permissions.manage_messages:
            return await i.response.send_message("Mods only.",ephemeral=True)
        row=await _pool.fetchrow("SELECT bug_rewards_this_month FROM muta_users WHERE user_id=$1",self.reporter_id)
        if row and (row["bug_rewards_this_month"] or 0)>=BUG_REWARD_LIMIT_PER_MONTH:
            return await i.response.send_message("This user hit the monthly bug reward limit.",ephemeral=True)
        await add_cash(self.reporter_id,BUG_REWARD_AMOUNT)
        await _pool.execute("UPDATE muta_users SET bug_rewards_this_month=COALESCE(bug_rewards_this_month,0)+1 WHERE user_id=$1",self.reporter_id)
        await i.response.edit_message(content=f"🛠️ Bug approved. <@{self.reporter_id}> received **{BUG_REWARD_AMOUNT}** cash.\n> {self.desc}",view=None)
    @button(label="Reject",style=discord.ButtonStyle.secondary,emoji="❌")
    async def reject(self,i:discord.Interaction,_):
        if not i.user.guild_permissions.manage_messages:
            return await i.response.send_message("Mods only.",ephemeral=True)
        await i.response.edit_message(content="Bug report rejected.",view=None)

# ================== ANNOUNCERS ==================
async def announce_youtube(video_id:str, title:str):
    g=bot.get_guild(GUILD_ID); ch=g.get_channel(YT_ANNOUNCE_CHANNEL_ID); role=g.get_role(YT_PING_ROLE_ID)
    if ch and role:
        embed=discord.Embed(title=title, url=f"https://youtu.be/{video_id}", color=0xE62117)
        embed.description = f"{role.mention} Mutapapa just released a new video called: {title} — Click to watch it!"
        embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
        await ch.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

async def announce_x(url:str, text:str|None):
    g=bot.get_guild(GUILD_ID); ch=g.get_channel(X_ANNOUNCE_CHANNEL_ID); role=g.get_role(X_PING_ROLE_ID)
    if ch and role:
        title = text or "New post on X"
        embed=discord.Embed(title=title, url=url, color=0x1DA1F2)
        embed.description = "Mutapapa just posted something on X (Formerly Twitter)! Click to check it out!"
        await ch.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

# ================== HELP ==================
def is_mod_or_admin(m:discord.Member)->bool:
    if m.guild_permissions.administrator: return True
    return any(r.id in HELP_MOD_ROLE_IDS for r in m.roles)

def build_commands_embed(author:discord.Member)->discord.Embed:
    mod = is_mod_or_admin(author)
    e = discord.Embed(title="📜 Commands", color=0x5865F2)
    e.add_field(
        name="Everyone",
        value="!ping\n!balance (aliases: !bal, !cashme, !mycash)\n!leaderboard\n!bugreport <desc>\n!countstatus\n!cash <4 words>",
        inline=False
    )
    if mod:
        e.add_field(
            name="Mods",
            value="!send <text>\n!sendreact <text>\n!gstart <dur> <winners> <title> <desc>\n!gend | !greroll\n"
                  "!countgoal <n> | !countnext <n> | !countreset\n!doublecash on|off\n!addcash|!removecash @user <amt> [reason]\n"
                  "!cash drop\n!level|!levelup @user <role>\n!delete\n!paid <claim_id>",
            inline=False
        )
    return e

# ================== CROSS-TRADE DETECTOR ==================
CROSS_PATTERNS = [
    r"\bbuy(?:ing)?\s+robux\b", r"\bsell(?:ing)?\s+robux\b",
    r"\bpaypal\b", r"\bcashapp\b", r"\bcrypto\b", r"\bbtc\b", r"\beth\b",
    r"\busd\s*for\s*robux\b", r"\bvenmo\b", r"\bzelle\b"
]
_user_cross_last = {}  # throttle user id -> last ts

@bot.event
async def on_message(m:discord.Message):
    if m.author.bot: return
    c = m.content.lower().strip()

    # help/ping quickies
    if c in ("!help","!commands"): return await m.channel.send(embed=build_commands_embed(m.author))
    if c=="!ping": return await m.channel.send("pong 🏓")

    # economy tick
    if m.guild and m.channel.id in EARN_CHANNEL_IDS and not c.startswith("!"):
        await earn_for_message(m.author.id, now_local(), len(m.content), m.guild, m.author.id)

    # counting strict digits
    if m.channel.id==COUNT_CHANNEL_ID and not re.fullmatch(r"\d+", m.content):
        try: await m.delete()
        except: pass

    # W/F/L auto reacts
    if m.channel.id==WFL_CHANNEL_ID and any(x in c for x in ("wfl","w/f/l","w f l")):
        for em in ("🇼","🇫","🇱"):
            try: await m.add_reaction(em)
            except: pass

    # cross-trade detect (exclude some categories)
    if m.guild and (m.channel.category_id not in CROSS_TRADE_EXCLUDED_CATEGORY_IDS):
        last = _user_cross_last.get(m.author.id, 0.0)
        if time() - last > 120:
            if any(re.search(p, c) for p in CROSS_PATTERNS):
                log = m.guild.get_channel(MOD_LOG_CHANNEL_ID)
                if log:
                    jump = f"https://discord.com/channels/{m.guild.id}/{m.channel.id}/{m.id}"
                    emb = discord.Embed(
                        title="🚨 Cross-trade Detected",
                        description=f"User: {m.author.mention}\nChannel: {m.channel.mention}\n[Jump to message]({jump})",
                        color=0xFF0000
                    )
                    excerpt = (m.content[:500] + "…") if len(m.content)>500 else m.content
                    emb.add_field(name="Excerpt", value=excerpt or "—", inline=False)
                    await log.send(embed=emb)
                _user_cross_last[m.author.id] = time()

    await bot.process_commands(m)

# ================== REACTION ROLES ==================
@bot.event
async def on_raw_reaction_add(p:discord.RawReactionActionEvent):
    if p.guild_id!=GUILD_ID or p.user_id==bot.user.id: return
    if p.channel_id != REACTION_ROLE_CHANNEL_ID: return
    role_id = REACTION_ROLE_MAP.get(str(p.emoji))
    if not role_id: return
    g=bot.get_guild(p.guild_id); m=g.get_member(p.user_id); r=g.get_role(role_id) if g else None
    if m and r and r not in m.roles:
        try: await m.add_roles(r, reason="Reaction role opt-in")
        except: pass

@bot.event
async def on_raw_reaction_remove(p:discord.RawReactionActionEvent):
    if p.guild_id!=GUILD_ID: return
    if p.channel_id != REACTION_ROLE_CHANNEL_ID: return
    role_id = REACTION_ROLE_MAP.get(str(p.emoji))
    if not role_id: return
    g=bot.get_guild(p.guild_id); m=g.get_member(p.user_id); r=g.get_role(role_id) if g else None
    if m and r and r in m.roles:
        try: await m.remove_roles(r, reason="Reaction role opt-out")
        except: pass

# ================== NEWCOMER PROMOTION ==================
@tasks.loop(minutes=10)
async def newcomer_promote_loop():
    g=bot.get_guild(GUILD_ID)
    if not g: return
    newcom=g.get_role(NEWCOMER_ROLE_ID); member_role=g.get_role(MEMBER_ROLE_ID)
    now=now_local()
    for m in g.members:
        try:
            if newcom in m.roles and m.joined_at and (now - m.joined_at.astimezone(TZ)) >= timedelta(days=3):
                await m.remove_roles(newcom, reason="Auto-promotion 3 days")
                await m.add_roles(member_role, reason="Auto-promotion 3 days")
        except: pass

@newcomer_promote_loop.before_loop
async def _before_promote(): await bot.wait_until_ready()

@bot.event
async def on_member_join(m:discord.Member):
    if m.bot or m.guild.id!=GUILD_ID: return
    newcom=m.guild.get_role(NEWCOMER_ROLE_ID)
    if newcom:
        try: await m.add_roles(newcom, reason="Newcomer on join")
        except: pass
    ch=m.guild.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        e=discord.Embed(title=f"Welcome to {m.guild.name}, {m.name}!",color=0x0089FF)
        e.set_thumbnail(url=m.display_avatar.url)
        if BANNER_URL: e.set_image(url=BANNER_URL)
        try: await ch.send(embed=e)
        except: pass

# ================== CASH DROPS (scheduled 3–4/day) ==================
def random_phrase(n=DROP_WORD_COUNT)->str:
    words=["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly",
           "kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango",
           "ultra","vivid","wax","xeno","yodel","zen"]
    return " ".join(random.choice(words) for _ in range(n))

def _schedule_key_for(date:datetime)->str:
    return f"drop_schedule_{date.astimezone(TZ).date().isoformat()}"

def _fired_key_for(date:datetime)->str:
    return f"drop_fired_{date.astimezone(TZ).date().isoformat()}"

def _times_today_local()->list[str]:
    # 3 or 4 random whole-minute times between 10:00 and 22:30 local
    k = random.choice([3,4])
    base = now_local().replace(hour=10, minute=0, second=0, microsecond=0)
    end = now_local().replace(hour=22, minute=30, second=0, microsecond=0)
    span_minutes = int((end - base).total_seconds()//60)
    mins = sorted(random.sample(range(span_minutes), k))
    return [(base + timedelta(minutes=m)).strftime("%H:%M") for m in mins]

async def ensure_today_drop_schedule():
    key = _schedule_key_for(now_local())
    val = await meta_get(key)
    if val: return json.loads(val)
    times = _times_today_local()
    await meta_set(key, json.dumps(times))
    await meta_set(_fired_key_for(now_local()), json.dumps([]))
    return times

async def mark_drop_fired(hhmm:str):
    k=_fired_key_for(now_local())
    fired = json.loads(await meta_get(k, "[]") or "[]")
    if hhmm not in fired:
        fired.append(hhmm)
        await meta_set(k, json.dumps(fired))

@tasks.loop(seconds=30)
async def scheduled_drops_loop():
    g=bot.get_guild(GUILD_ID)
    if not g: return
    ch=g.get_channel(CASH_DROP_CHANNEL_ID)
    if not ch: return
    times = await ensure_today_drop_schedule()
    fired = json.loads(await meta_get(_fired_key_for(now_local()), "[]") or "[]")
    now_hhmm = now_local().strftime("%H:%M")
    # fire if time matches and not yet fired (allow minute-level matching)
    if now_hhmm in times and now_hhmm not in fired:
        phrase = random_phrase()
        embed=discord.Embed(
            title="[Cash] Cash drop!",
            description=f"Type `!cash {phrase}` to collect **{DROP_AMOUNT}** cash!",
            color=0x2ECC71
        )
        try:
            msg=await ch.send(embed=embed)
            await _pool.execute("""INSERT INTO muta_drops(channel_id,message_id,phrase,amount,created_at)
                                   VALUES($1,$2,$3,$4,NOW())""",
                                ch.id, msg.id, phrase.lower(), DROP_AMOUNT)
        except: pass
        await mark_drop_fired(now_hhmm)

    # new schedule at 00:01 local
    if now_local().hour==0 and now_local().minute==1:
        await ensure_today_drop_schedule()

# ================== MONTHLY SEASON RESET ==================
@tasks.loop(minutes=1)
async def monthly_reset_loop():
    now=now_local(); next_minute=now+timedelta(minutes=1)
    if now.hour==23 and now.minute==59 and next_minute.day==1:
        rows=await leaderboard_top(10)
        # snapshot to multiple channels
        desc="\n".join(f"**{i}.** <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows,start=1)) if rows else "No data."
        for cid in SEASON_ANNOUNCE_CHANNEL_IDS:
            ch=bot.get_channel(cid)
            if ch:
                try:
                    await ch.send(embed=discord.Embed(title="🏁 Season ended — Final Top 10",description=desc,color=0xF39C12))
                    await ch.send("🧹 Balances reset. New season starts now — good luck!")
                except: pass
        await _pool.execute("UPDATE muta_users SET cash=0,today_earned=0")

# ================== COMMANDS ==================
@bot.command()
async def send(ctx, *, text:str):
    if not is_mod_or_admin(ctx.author): return
    await ctx.send(text)
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def sendreact(ctx, *, text:str):
    if not is_mod_or_admin(ctx.author): return
    if ctx.channel.id != REACTION_ROLE_CHANNEL_ID:
        await ctx.send("Use this in the reaction-role channel.")
        return
    msg = await ctx.send(text)
    for em in REACTION_ROLE_MAP.keys():
        try: await msg.add_reaction(em)
        except: pass
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def delete(ctx):
    if ctx.guild and not is_mod_or_admin(ctx.author): return
    async for m in ctx.channel.history(limit=50):
        if m.author==bot.user:
            try: await m.delete()
            except: pass
            break
    try: await ctx.message.delete()
    except: pass

@bot.command(aliases=["add"])
async def addcash(ctx,user:discord.Member,amount:int,*,reason="Adjustment"):
    if not is_mod_or_admin(ctx.author): return
    bal=await add_cash(user.id,amount)
    await ctx.send(f"➕ Added **{amount}** cash to {user.mention}. Reason: {reason} (bal: {bal})")
    try: await ctx.message.delete()
    except: pass

@bot.command(aliases=["remove"])
async def removecash(ctx,user:discord.Member,amount:int,*,reason="Adjustment"):
    if not is_mod_or_admin(ctx.author): return
    bal=await deduct_cash(user.id,amount)
    await ctx.send(f"➖ Removed **{amount}** cash from {user.mention}. Reason: {reason} (bal: {bal})")
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def doublecash(ctx,switch:str):
    if not is_mod_or_admin(ctx.author): return
    global DOUBLE_CASH; DOUBLE_CASH = (switch.lower()=="on")
    await ctx.send(f"Double cash is now {'ON' if DOUBLE_CASH else 'OFF'}.")
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def cashdrop(ctx,amount:int=DROP_AMOUNT):
    if not is_mod_or_admin(ctx.author): return
    ch = bot.get_channel(CASH_DROP_CHANNEL_ID) or ctx.channel
    phrase=random_phrase()
    emb=discord.Embed(title="[Cash] Cash drop!",description=f"Type `!cash {phrase}` to collect **{amount}** cash!",color=0x2ECC71)
    msg=await ch.send(embed=emb)
    await _pool.execute("INSERT INTO muta_drops(channel_id,message_id,phrase,amount,created_at) VALUES($1,$2,$3,$4,NOW())",
                        ch.id,msg.id,phrase.lower(),amount)
    try: await ctx.message.delete()
    except: pass

@bot.command(aliases=["level"])
async def levelup(ctx,user:discord.Member,role:str):
    if not is_mod_or_admin(ctx.author): return
    roles={"rookie":ROLE_ROOKIE,"squad":ROLE_SQUAD,"specialist":ROLE_SPECIALIST,"operative":ROLE_OPERATIVE,"legend":ROLE_LEGEND}
    rid=roles.get(role.lower())
    if not rid: return await ctx.send("Role must be one of: Rookie, Squad, Specialist, Operative, Legend")
    r=ctx.guild.get_role(rid)
    if r:
        await user.add_roles(r,reason="Manual level up")
        ch=ctx.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
        if ch: await ch.send(f"{user.mention} reached the **{r.name}** role! 🎉")
    try: await ctx.message.delete()
    except: pass

# Counting controls
@bot.command()
async def countgoal(ctx,n:int):
    if not is_mod_or_admin(ctx.author): return
    global COUNT_GOAL; COUNT_GOAL=n
    await ctx.send(f"✅ Goal set to **{n}**.")
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def countnext(ctx,n:int):
    if not is_mod_or_admin(ctx.author): return
    global COUNT_NEXT; COUNT_NEXT=n
    await ctx.send(f"✅ Next expected number set to **{n}**.")
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def countreset(ctx):
    if not is_mod_or_admin(ctx.author): return
    global COUNT_NEXT; COUNT_NEXT=1
    await ctx.send("✅ Counter reset to **1**.")
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def countstatus(ctx):
    await ctx.send(f"Next expected: **{COUNT_NEXT}** | Goal: **{COUNT_GOAL}**")

# Giveaways
@bot.command()
async def gstart(ctx,duration:str,winners:int,title:str="Giveaway",*,desc:str=""):
    if not is_mod_or_admin(ctx.author): return
    # duration like "1h", "30m"
    unit = duration[-1:].lower()
    try:
        num = int(duration[:-1])
        dur_s = num * (3600 if unit=="h" else 60 if unit=="m" else 1)
    except:
        return await ctx.send("Usage: `!gstart 1h 1 Title Desc`")
    ends=time()+dur_s
    emb=discord.Embed(title=title,description=desc,color=0x5865F2)
    emb.add_field(name="Duration",value=duration); emb.add_field(name="Winners",value=str(winners))
    msg=await ctx.send(embed=emb,view=GiveawayView(0))
    GIVEAWAYS[str(msg.id)]={"channel_id":ctx.channel.id,"ends_at":ends,"winners":winners,"title":title,"desc":desc,"participants":[],"ended":False}
    await msg.edit(view=GiveawayView(msg.id))
    asyncio.create_task(schedule_giveaway_end(msg.id,ends))
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def gend(ctx):
    if not is_mod_or_admin(ctx.author): return
    active=[int(mid) for mid,g in GIVEAWAYS.items() if not g.get("ended")]
    if not active: return await ctx.send("No active giveaways.")
    await end_giveaway(max(active)); await ctx.send("✅ Giveaway ended.")
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def greroll(ctx):
    if not is_mod_or_admin(ctx.author): return
    any_g=[int(mid) for mid in GIVEAWAYS.keys()]
    if not any_g: return await ctx.send("No giveaways.")
    await end_giveaway(max(any_g)); await ctx.send("✅ Rerolled.")
    try: await ctx.message.delete()
    except: pass

# Public
@bot.command()
async def bugreport(ctx,*,desc:str):
    if len(desc)<5: return await ctx.send("Please include a description.")
    ch=ctx.guild.get_channel(BUG_REVIEW_CHANNEL_ID)
    if not ch: return await ctx.send("Bug review channel not found.")
    await ch.send(content=f"🐞 New bug from {ctx.author.mention}:\n> {desc}",view=BugApproveView(ctx.author.id,desc))
    await ctx.send("Submitted for review!")
    try: await ctx.message.delete()
    except: pass

@bot.command(aliases=["bal","mycash","cashme"])
async def balance(ctx):
    row=await _pool.fetchrow("SELECT cash FROM muta_users WHERE user_id=$1",ctx.author.id) or {"cash":0}
    await ctx.send(f"💰 {ctx.author.mention} balance: **{row['cash']}**")

@bot.command()
async def leaderboard(ctx):
    rows=await leaderboard_top(10)
    if not rows: return await ctx.send("No data yet.")
    desc="\n".join(f"**{i}.** <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows,start=1))
    await ctx.send(embed=discord.Embed(title="🏆 Top 10",description=desc,color=0xF1C40F))

@bot.command()
async def cash(ctx,*,phrase:str=""):
    if not phrase: return await ctx.send(f"Usage: `!cash <{DROP_WORD_COUNT} words>`")
    row=await _pool.fetchrow("SELECT id,amount FROM muta_drops WHERE phrase=$1 AND claimed_by IS NULL ORDER BY created_at DESC LIMIT 1", phrase.lower())
    if not row: return await ctx.send("That drop was already claimed or not found.")
    await _pool.execute("UPDATE muta_drops SET claimed_by=$1,claimed_at=NOW() WHERE id=$2 AND claimed_by IS NULL", ctx.author.id, row["id"])
    bal=await add_cash(ctx.author.id,row["amount"])
    await ctx.send(f"💸 {ctx.author.mention} claimed **{row['amount']}** cash! (bal: {bal})")

# ================== YT WebSub + X/YouTube polling ==================
routes = web.RouteTableDef()

@routes.get("/health")
async def health(_):
    return web.json_response({"ok": True, "time": utc_now().isoformat()})

def verify_websub_signature(secret: str, body: bytes, header: str|None) -> bool:
    if not header: return False
    # header like: "sha1=abcdef..."
    try:
        algo, hexdigest = header.split("=",1)
        if algo.lower()!="sha1": return False
        digest = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
        return hmac.compare_digest(digest, hexdigest)
    except: return False

@routes.get("/yt/webhook")
async def yt_sub_get(request: web.Request):
    # verification challenge
    hub_challenge = request.rel_url.query.get("hub.challenge")
    if hub_challenge: return web.Response(text=hub_challenge)
    return web.Response(text="ok")

@routes.post("/yt/webhook")
async def yt_sub_post(request: web.Request):
    body = await request.read()
    sig = request.headers.get("X-Hub-Signature")
    if not verify_websub_signature(YT_WEBHOOK_SECRET, body, sig):
        return web.Response(status=403, text="bad-signature")
    # very light parse; just store "got update" and let polling confirm
    await meta_set("yt_webhook_last", utc_now().isoformat())
    return web.Response(text="ok")

async def start_webserver():
    global web_runner
    app = web.Application()
    app.add_routes(routes)
    web_runner = web.AppRunner(app)
    await web_runner.setup()
    site = web.TCPSite(web_runner, host="0.0.0.0", port=PORT)
    await site.start()

@tasks.loop(minutes=5)
async def yt_poll_loop():
    # Basic fallback: fetch channel uploads (RSS) and check newest id change.
    # Note: Shorts also expose videoId in RSS.
    feed_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCSLxLMfxnFRxyhNOZMy4i9w"
    try:
        async with http.get(feed_url, timeout=20) as r:
            if r.status!=200: return
            text = await r.text()
            # naive find of latest video id and title
            vid_match = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", text)
            title_match = re.search(r"<title>([^<]+)</title>", text)
            if not vid_match or not title_match: return
            video_id = vid_match.group(1)
            title = title_match.group(1)
            last = await meta_get("yt_last_video_id", "")
            if video_id and video_id != last:
                await meta_set("yt_last_video_id", video_id)
                await announce_youtube(video_id, title)
    except: pass

@tasks.loop(minutes=6)
async def x_poll_loop():
    # poll Nitter RSS (configurable); store last item id to avoid duplicates
    try:
        async with http.get(X_RSS_URL, timeout=20, headers={"User-Agent":"Mozilla/5.0"}) as r:
            if r.status!=200: return
            text = await r.text()
            guid = None
            m = re.search(r"<guid[^>]*>([^<]+)</guid>", text)
            if m: guid = m.group(1)
            if not guid: return
            last = await meta_get("x_last_guid","")
            if guid != last:
                await meta_set("x_last_guid", guid)
                # try extract tweet url + title
                link_m = re.search(r"<link>(https?://[^<]+)</link>", text)
                title_m = re.search(r"<title>([^<]+)</title>", text)
                url = link_m.group(1) if link_m else "https://x.com/Real_Mutapapa"
                title = title_m.group(1) if title_m else "New post on X"
                # Prefer canonical x.com if we can parse status id
                id_m = re.search(r"/status/(\d+)", url)
                if id_m:
                    url = f"https://x.com/Real_Mutapapa/status/{id_m.group(1)}"
                await announce_x(url, title)
    except: pass

# ================== READY / STARTUP ==================
@bot.event
async def on_ready():
    print(f"Ready as {bot.user}")
    await db_init()

    # start HTTP session + web server
    global http
    if http is None: http = aiohttp.ClientSession()
    await start_webserver()

    # loops
    if not newcomer_promote_loop.is_running(): newcomer_promote_loop.start()
    if not scheduled_drops_loop.is_running(): scheduled_drops_loop.start()
    if not monthly_reset_loop.is_running(): monthly_reset_loop.start()
    if not yt_poll_loop.is_running(): yt_poll_loop.start()
    if not x_poll_loop.is_running(): x_poll_loop.start()

    # giveaway claims cog
    if not bot.get_cog("GiveawayClaims"): await setup_giveaway_claims(bot,_pool)

# ================== RUN ==================
def main():
    t=os.getenv("DISCORD_TOKEN")
    if not t: raise RuntimeError("DISCORD_TOKEN missing")
    bot.run(t)

if __name__=="__main__":
    main()