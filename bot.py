# bot.py
import os, re, hmac, hashlib, json, random, asyncio, xml.etree.ElementTree as ET
from time import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import aiohttp
import asyncpg
import discord
from discord.ext import commands, tasks
from discord.ui import View, button

# ================== CORE CONFIG ==================
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
TZ = ZoneInfo("America/Edmonton")

def utc_now(): return datetime.now(timezone.utc)

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
        await i.response.send_message("Thanks! Sent to Mutapapa 🎉")
        await self.cog._dm_admin_with_claim(self.claim_id,answers)

class ClaimStartView(discord.ui.View):
    def __init__(self,cog,claim_id:int): super().__init__(timeout=None); self.cog=cog; self.claim_id=claim_id
    @discord.ui.button(label="Open Claim Form",style=discord.ButtonStyle.primary)
    async def open_form(self,i:discord.Interaction,_): await i.response.send_modal(ClaimFormModal(self.cog,self.claim_id))

class GiveawayClaims(commands.Cog):
    def __init__(self,bot,pool): self.bot=bot; self.pool=pool; self._expiry.start()
    def cog_unload(self): self._expiry.cancel()
    async def start_claim_for_winner(self,guild,winner,title,announce,fallback):
        exp=(datetime.now(TZ)+timedelta(hours=24)).astimezone(timezone.utc)
        rec=await self.pool.fetchrow("INSERT INTO muta_giveaway_claims(guild_id,giveaway_title,winner_id,expires_at) VALUES($1,$2,$3,$4) RETURNING id",guild.id,title,winner.id,exp)
        cid=rec["id"]
        try: await winner.send(f"Congrats {winner.mention}! You won **{title}** 🎉\nType `claim` or press button within 24h.",view=ClaimStartView(self,cid))
        except discord.Forbidden:
            if announce: await announce.edit(content=announce.content+f"\n⚠️ <@{winner.id}> DM <@{ADMIN_USER_ID}> within 24h")
            elif fallback: await fallback.send(f"⚠️ <@{winner.id}> DM <@{ADMIN_USER_ID}> to claim **{title}**")
    @commands.Cog.listener("on_message")
    async def _listen(self,m:discord.Message):
        if m.guild or m.author.bot: return
        if "claim" not in m.content.lower(): return
        row=await self.pool.fetchrow("SELECT id FROM muta_giveaway_claims WHERE winner_id=$1 AND status='pending' ORDER BY created_at DESC LIMIT 1",m.author.id)
        if row: await m.channel.send("Tap to claim.",view=ClaimStartView(self,row["id"]))
    async def _save_answers(self,cid:int,a:dict): await self.pool.execute("UPDATE muta_giveaway_claims SET answers=$2,status='submitted' WHERE id=$1",cid,json.dumps(a))
    async def _dm_admin_with_claim(self,cid:int,a:dict):
        admin=self.bot.get_user(ADMIN_USER_ID) or await self.bot.fetch_user(ADMIN_USER_ID)
        row=await self.pool.fetchrow("SELECT giveaway_title,winner_id FROM muta_giveaway_claims WHERE id=$1",cid)
        if not row: return
        try: await admin.send(f"**Claim {cid}**\nTitle: {row['giveaway_title']}\nWinner: <@{row['winner_id']}>\nRoblox: {a.get('roblox')}\nItem: {a.get('item') or '—'}\nNotes: {a.get('notes') or '—'}\n\nReply `!paid {cid}` when done.")
        except: pass
    @commands.command(name="paid")
    async def mark_paid(self,ctx,cid:int):
        if ctx.author.id!=ADMIN_USER_ID and not ctx.author.guild_permissions.administrator: return
        row=await self.pool.fetchrow("UPDATE muta_giveaway_claims SET status='paid' WHERE id=$1 AND status IN('pending','submitted') RETURNING winner_id,giveaway_title",cid)
        if not row: return await ctx.reply("No such claim.")
        try: (await self.bot.fetch_user(row["winner_id"])).send(f"Your giveaway **{row['giveaway_title']}** has been paid. DM <@{ADMIN_USER_ID}> if issues.")
        except: pass
        await ctx.reply(f"Claim {cid} marked paid.")
    @tasks.loop(minutes=10)
    async def _expiry(self): await self.pool.execute("UPDATE muta_giveaway_claims SET status='expired' WHERE status IN('pending','submitted') AND expires_at<NOW()")

def setup_giveaway_claims(bot,pool):
    if not bot.get_cog("GiveawayClaims"): bot.add_cog(GiveawayClaims(bot,pool))

# ================== IDS ==================
GUILD_ID=1411205177880608831
WELCOME_CHANNEL_ID=1411946767414591538
NEWCOMER_ROLE_ID=1411957261009555536
MEMBER_ROLE_ID=1411938410041708585
MOD_LOG_CHANNEL_ID=1413297073348018299
LEVEL_UP_ANNOUNCE_CHANNEL_ID=1415505829401989131
REACTION_CHANNEL_ID=1414001588091093052
REACTION_ROLE_MAP={"📺":1412989373556850829,"🔔":1412993171670958232,"✖️":1414001344297172992,"🎉":1412992931148595301}
WFL_CHANNEL_ID=1411931034026643476
COUNT_CHANNEL_ID=1414051875329802320
CROSS_TRADE_EXCLUDED_CATEGORY_IDS={1411935087867723826,1411206110895149127,1413998743682023515}
YT_CHANNEL_ID="UCSLxLMfxnFRxyhNOZMy4i9w"; YT_ANNOUNCE_CHANNEL_ID=1412144563144888452; YT_PING_ROLE_ID=1412989373556850829
X_USERNAME="Real_Mutapapa"; X_ANNOUNCE_CHANNEL_ID=1414000975680897128; X_PING_ROLE_ID=1414001344297172992

# ================== ECONOMY CONFIG ==================
EARN_CHANNEL_IDS=[1411930638260502638,1411486271464935456,1413297073348018299,1411935203953217566,1411435784250331288,1412144563144888452,1411931216608755782,1414000975680897128,1411433941403177054,1411931171671117854,1411946767414591538,1413999346592256050,1414001588091093052]
EARN_COOLDOWN_SEC=180; EARN_PER_TICK=200; DAILY_CAP=2000; DOUBLE_CASH=False
DROP_AMOUNT=225; DROP_WORD_COUNT=4
BUG_REWARD_AMOUNT=350; BUG_REWARD_LIMIT_PER_MONTH=2

# ================== LEVEL ROLES ==================
ROLE_ROOKIE=1414817524557549629; ROLE_SQUAD=1414818303028891731; ROLE_SPECIALIST=1414818845541138493; ROLE_OPERATIVE=1414819588448718880; ROLE_LEGEND=1414819897602474057
ACTIVITY_THRESHOLDS=[(ROLE_ROOKIE,5000),(ROLE_SQUAD,25000),(ROLE_SPECIALIST,75000),(ROLE_OPERATIVE,180000),(ROLE_LEGEND,400000)]
HELP_MOD_ROLE_IDS={1413663966349234320,1411940485005578322,1413991410901713088}

# ================== DB INIT ==================
DB_URL=os.getenv("SUPABASE_DB_URL","").strip(); _pool=None
async def db_init():
    global _pool; _pool=await asyncpg.create_pool(dsn=DB_URL,min_size=1,max_size=5)
    async with _pool.acquire() as con:
        await con.execute("CREATE TABLE IF NOT EXISTS muta_meta(key TEXT PRIMARY KEY,value TEXT)")
        await con.execute("CREATE TABLE IF NOT EXISTS muta_users(user_id BIGINT PRIMARY KEY,cash BIGINT DEFAULT 0,last_earn_ts TIMESTAMPTZ,today_earned BIGINT DEFAULT 0,bug_rewards_this_month INT DEFAULT 0,activity_points BIGINT DEFAULT 0)")
        await con.execute("CREATE TABLE IF NOT EXISTS muta_drops(id BIGSERIAL PRIMARY KEY,channel_id BIGINT,message_id BIGINT UNIQUE,phrase TEXT,amount INT,claimed_by BIGINT,claimed_at TIMESTAMPTZ,created_at TIMESTAMPTZ DEFAULT NOW())")
        await con.execute("CREATE TABLE IF NOT EXISTS muta_giveaway_claims(id BIGSERIAL PRIMARY KEY,guild_id BIGINT,giveaway_title TEXT,winner_id BIGINT,status TEXT DEFAULT 'pending',created_at TIMESTAMPTZ DEFAULT NOW(),expires_at TIMESTAMPTZ,answers JSONB DEFAULT '{}'::jsonb)")

# ================== DISCORD CLIENT ==================
intents=discord.Intents.default(); intents.message_content=True; intents.members=True
bot=commands.Bot(command_prefix="!",intents=intents)

# (Part 2 below…)
# ================== ECONOMY FUNCTIONS ==================
async def ensure_user(uid:int):
    await _pool.execute("INSERT INTO muta_users(user_id) VALUES($1) ON CONFLICT DO NOTHING",uid)

async def add_cash(uid:int,amount:int)->int:
    await ensure_user(uid)
    row=await _pool.fetchrow("UPDATE muta_users SET cash=cash+$1 WHERE user_id=$2 RETURNING cash",amount,uid)
    return int(row["cash"]) if row else 0

async def deduct_cash(uid:int,amount:int)->int:
    await ensure_user(uid)
    row=await _pool.fetchrow("UPDATE muta_users SET cash=GREATEST(0,cash-$1) WHERE user_id=$2 RETURNING cash",amount,uid)
    return int(row["cash"]) if row else 0

async def leaderboard_top(n=10):
    return await _pool.fetch("SELECT user_id,cash FROM muta_users ORDER BY cash DESC LIMIT $1",n)

async def earn_for_message(uid:int,now:datetime,msg_len:int,guild,author_id:int):
    await ensure_user(uid)
    row=await _pool.fetchrow("SELECT cash,last_earn_ts,today_earned,activity_points FROM muta_users WHERE user_id=$1",uid)
    last_ts=row["last_earn_ts"]; today=int(row["today_earned"] or 0); points=int(row["activity_points"] or 0)
    if last_ts and last_ts.astimezone(TZ).date()!=now.date(): today=0
    if today>=DAILY_CAP: return 0
    if last_ts and (now-last_ts).total_seconds()<EARN_COOLDOWN_SEC: return 0
    bonus=0 if msg_len<=9 else 50 if msg_len<=49 else 80 if msg_len<=99 else 100
    grant=min((EARN_PER_TICK+bonus)*(2 if DOUBLE_CASH else 1),DAILY_CAP-today)
    await _pool.execute("UPDATE muta_users SET cash=cash+$1,last_earn_ts=$2,today_earned=$3,activity_points=$4 WHERE user_id=$5",
        grant,now,today+grant,points+grant,uid)
    if guild:
        member=guild.get_member(author_id)
        if member: await assign_activity_roles(member,points+grant)
    return grant

async def assign_activity_roles(member:discord.Member,points:int):
    granted=[]
    for rid,th in ACTIVITY_THRESHOLDS:
        if points>=th:
            role=member.guild.get_role(rid)
            if role and role not in member.roles: granted.append(role)
    if granted:
        await member.add_roles(*granted,reason="Activity level up")
        ch=member.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
        if ch: await ch.send(f"{member.mention} reached the **{granted[-1].name}** role! 🎉")

# ================== GIVEAWAYS ==================
GIVEAWAYS={}
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

async def schedule_giveaway_end(mid:int,ends:float): await asyncio.sleep(max(0,ends-time())); await end_giveaway(mid)

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
            claims=bot.get_cog("GiveawayClaims"); 
            if not claims: setup_giveaway_claims(bot,_pool); claims=bot.get_cog("GiveawayClaims")
            for w in winners:
                u=ch.guild.get_member(w)
                if u: await claims.start_claim_for_winner(ch.guild,u,gw["title"],sent,ch)
        else: await ch.send("No entries.")
    gw["ended"]=True; GIVEAWAYS[str(mid)]=gw

# ================== ANNOUNCERS ==================
async def announce_youtube(video_id,title):
    g=bot.get_guild(GUILD_ID); ch=g.get_channel(YT_ANNOUNCE_CHANNEL_ID); role=g.get_role(YT_PING_ROLE_ID)
    if ch and role:
        embed=discord.Embed(title=title,url=f"https://youtu.be/{video_id}",color=0xE62117)
        embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
        await ch.send(content=f"{role.mention} Mutapapa just released a new video!",embed=embed,allowed_mentions=discord.AllowedMentions(roles=True))

async def announce_x(url,text):
    g=bot.get_guild(GUILD_ID); ch=g.get_channel(X_ANNOUNCE_CHANNEL_ID); role=g.get_role(X_PING_ROLE_ID)
    if ch and role:
        embed=discord.Embed(title=text or "New post on X",url=url,color=0x1DA1F2)
        await ch.send(content=f"{role.mention} Mutapapa just posted on X!",embed=embed,allowed_mentions=discord.AllowedMentions(roles=True))

# ================== HELP ==================
def build_commands_embed(author:discord.Member)->discord.Embed:
    mod=author.guild_permissions.administrator or any(r.id in HELP_MOD_ROLE_IDS for r in author.roles)
    e=discord.Embed(title="📜 Commands",color=0x5865F2)
    e.add_field(name="Everyone",value="!ping\n!balance\n!leaderboard\n!bugreport <desc>\n!countstatus\n!cash <4 words>",inline=False)
    if mod: e.add_field(name="Mods",value="!send\n!sendreact\n!gstart | !gend | !greroll\n!countgoal|!countnext|!countreset\n!doublecash on/off\n!addcash|!removecash\n!cash drop\n!levelup @user <role>\n!delete\n!paid <claim_id>",inline=False)
    return e

# ================== CROSS-TRADE DETECTOR ==================
CROSS_PATTERNS=[r"buy(ing)? robux",r"sell(ing)? robux",r"paypal",r"cashapp",r"crypto",r"btc",r"eth",r"usd ?for robux"]
@bot.event
async def on_message(m:discord.Message):
    if m.author.bot: return
    c=m.content.lower().strip()
    if c in ("!help","!commands"): return await m.channel.send(embed=build_commands_embed(m.author))
    if c=="!ping": return await m.channel.send("pong 🏓")
    if c in ("!balance","!bal","!mycash"):
        row=await _pool.fetchrow("SELECT cash FROM muta_users WHERE user_id=$1",m.author.id) or {"cash":0}
        return await m.channel.send(f"💰 {m.author.mention} balance: **{row['cash']}**")
    # earn cash
    if m.guild and m.channel.id in EARN_CHANNEL_IDS and not c.startswith("!"):
        await earn_for_message(m.author.id,datetime.now(tz=TZ),len(m.content),m.guild,m.author.id)
    # counting
    if m.channel.id==COUNT_CHANNEL_ID and not re.fullmatch(r"\d+",m.content): await m.delete()
    # W/F/L auto reacts
    if m.channel.id==WFL_CHANNEL_ID and any(x in c for x in ("wfl","w/f/l")):
        for em in ("🇼","🇫","🇱"): await m.add_reaction(em)
    # cross-trade detect
    if m.guild and m.channel.category_id not in CROSS_TRADE_EXCLUDED_CATEGORY_IDS:
        if any(re.search(p,c) for p in CROSS_PATTERNS):
            log=m.guild.get_channel(MOD_LOG_CHANNEL_ID)
            if log: await log.send(embed=discord.Embed(title="🚨 Cross-trade Detected",description=f"User: {m.author.mention}\nChannel: {m.channel.mention}\nContent: {m.content[:200]}",color=0xFF0000))

# ================== REACTION ROLES ==================
@bot.event
async def on_raw_reaction_add(p:discord.RawReactionActionEvent):
    if p.guild_id!=GUILD_ID or p.user_id==bot.user.id: return
    role_id=REACTION_ROLE_MAP.get(str(p.emoji)); 
    if not role_id: return
    g=bot.get_guild(p.guild_id); m=g.get_member(p.user_id); r=g.get_role(role_id) if g else None
    if m and r and r not in m.roles: await m.add_roles(r)

@bot.event
async def on_raw_reaction_remove(p:discord.RawReactionActionEvent):
    if p.guild_id!=GUILD_ID: return
    role_id=REACTION_ROLE_MAP.get(str(p.emoji))
    if not role_id: return
    g=bot.get_guild(p.guild_id); m=g.get_member(p.user_id); r=g.get_role(role_id) if g else None
    if m and r and r in m.roles: await m.remove_roles(r)

# ================== NEWCOMER PROMOTION ==================
@tasks.loop(minutes=10)
async def newcomer_promote_loop():
    g=bot.get_guild(GUILD_ID)
    if not g: return
    newcom=g.get_role(NEWCOMER_ROLE_ID); member_role=g.get_role(MEMBER_ROLE_ID)
    now=datetime.now(tz=TZ)
    for m in g.members:
        if newcom in m.roles and m.joined_at and (now-m.joined_at.astimezone(TZ))>=timedelta(days=3):
            await m.remove_roles(newcom); await m.add_roles(member_role)

@newcomer_promote_loop.before_loop
async def before_promote(): await bot.wait_until_ready()

@bot.event
async def on_member_join(m:discord.Member):
    if m.bot or m.guild.id!=GUILD_ID: return
    newcom=m.guild.get_role(NEWCOMER_ROLE_ID)
    if newcom: await m.add_roles(newcom)
    ch=m.guild.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        e=discord.Embed(title=f"Welcome to {m.guild.name}, {m.name}!",color=0x0089FF)
        e.set_thumbnail(url=m.display_avatar.url); await ch.send(embed=e)

# ================== READY ==================
@bot.event
async def on_ready():
    print(f"Ready as {bot.user}")
    await db_init()
    if not newcomer_promote_loop.is_running(): newcomer_promote_loop.start()
    if not bot.get_cog("GiveawayClaims"): setup_giveaway_claims(bot,_pool)

# ================== RUN ==================
def main():
    t=os.getenv("DISCORD_TOKEN"); 
    if not t: raise RuntimeError("DISCORD_TOKEN missing")
    bot.run(t)

if __name__=="__main__": main()
