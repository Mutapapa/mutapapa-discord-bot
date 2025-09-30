# bot.py
import os, re, json, random, asyncio, aiohttp
from time import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import discord
from discord.ext import commands, tasks
from discord.ui import View, button
from aiohttp import web

# ================== CORE CONFIG ==================
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
TZ = ZoneInfo("America/Edmonton")
def utc_now(): return datetime.now(timezone.utc)
def now_local(): return datetime.now(TZ)

# ================== GUILD / IDS ==================
GUILD_ID=1411205177880608831
WELCOME_CHANNEL_ID=1411946767414591538
NEWCOMER_ROLE_ID=1411957261009555536
MEMBER_ROLE_ID=1411938410041708585
MOD_LOG_CHANNEL_ID=1413297073348018299
LEVEL_UP_ANNOUNCE_CHANNEL_ID=1415505829401989131
CASH_DROP_CHANNEL_ID=1414120740327788594
BUG_REVIEW_CHANNEL_ID=1414124214956593242
PENALTY_APPROVALS_CHANNEL_ID=1414124795418640535
REACTION_ROLE_MAP={"📺":1412989373556850829,"🔔":1412993171670958232,"✖️":1414001344297172992,"🎉":1412992931148595301}
WFL_CHANNEL_ID=1411931034026643476
COUNT_CHANNEL_ID=1414051875329802320
CROSS_TRADE_EXCLUDED_CATEGORY_IDS={1411935087867723826,1411206110895149127,1413998743682023515}
YT_ANNOUNCE_CHANNEL_ID=1412144563144888452; YT_PING_ROLE_ID=1412989373556850829
X_ANNOUNCE_CHANNEL_ID=1414000975680897128; X_PING_ROLE_ID=1414001344297172992

# ================== ECONOMY / LEVELS CONFIG ==================
EARN_CHANNEL_IDS=[1411930638260502638,1411486271464935456,1413297073348018299,1411935203953217566,1411435784250331288,1412144563144888452,1411931216608755782,1414000975680897128,1411433941403177054,1411931171671117854,1411946767414591538,1413999346592256050,1414001588091093052]
EARN_COOLDOWN_SEC=180
EARN_PER_TICK=200
DAILY_CAP=2000
DOUBLE_CASH=False

DROP_AMOUNT=225
DROP_WORD_COUNT=4

BUG_REWARD_AMOUNT=350
BUG_REWARD_LIMIT_PER_MONTH=2

ROLE_ROOKIE=1414817524557549629
ROLE_SQUAD=1414818303028891731
ROLE_SPECIALIST=1414818845541138493
ROLE_OPERATIVE=1414819588448718880
ROLE_LEGEND=1414819897602474057
ACTIVITY_THRESHOLDS=[(ROLE_ROOKIE,5000),(ROLE_SQUAD,25000),(ROLE_SPECIALIST,75000),(ROLE_OPERATIVE,180000),(ROLE_LEGEND,400000)]

HELP_MOD_ROLE_IDS={1413663966349234320,1411940485005578322,1413991410901713088}

TRADE_PATTERNS=[r"paypal",r"cashapp",r"venmo",r"crypto",r"buy.*robux",r"sell.*robux"]
_last_trade_trigger={}

# ================== YT / X CONFIG ==================
YT_CHANNEL_ID = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_SECRET = "mutapapa-youtube"
BANNER_URL = os.getenv("BANNER_URL","")
X_USER = "Real_Mutapapa"
X_RSS_URL = os.getenv("X_RSS_URL", f"https://nitter.net/{X_USER}/rss")

# ================== DB INIT ==================
DB_URL=os.getenv("SUPABASE_DB_URL","").strip()
_pool: asyncpg.Pool | None = None

async def db_init():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=DB_URL, min_size=1, max_size=5,
        statement_cache_size=0  # PgBouncer (transaction/statement) safe
    )
    async with _pool.acquire() as con:
        await con.execute("CREATE TABLE IF NOT EXISTS muta_meta(key TEXT PRIMARY KEY,value TEXT)")
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

# ================== HELPERS ==================
async def meta_get(key: str, default=None):
    row = await _pool.fetchrow("SELECT value FROM muta_meta WHERE key=$1", key)
    return json.loads(row["value"]) if row else default

async def meta_set(key: str, val):
    await _pool.execute(
        "INSERT INTO muta_meta(key,value) VALUES($1,$2) ON CONFLICT (key) DO UPDATE SET value=$2",
        key, json.dumps(val)
    )

async def cleanup_message(ctx):
    try: await ctx.message.delete()
    except: pass

# ================== ECONOMY CORE ==================
async def add_cash(user_id:int,amount:int,activity_pts:int=0):
    await _pool.execute(
        """INSERT INTO muta_users(user_id,cash,activity_points) 
           VALUES($1,$2,$3) 
           ON CONFLICT (user_id) DO UPDATE 
           SET cash=muta_users.cash+EXCLUDED.cash,
               activity_points=muta_users.activity_points+EXCLUDED.activity_points""",
        user_id,amount,activity_pts)

async def get_balance(user_id:int):
    row=await _pool.fetchrow("SELECT cash FROM muta_users WHERE user_id=$1",user_id)
    return int(row["cash"]) if row else 0

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

class ClaimStartView(View):
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
                f"Congrats {winner.mention}! You won **{title}** 🎉\n"
                f"Type `claim` or press the button within 24h.", view=ClaimStartView(self,cid)
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
                f"**Claim {cid}**\nTitle: {row['giveaway_title']}\nWinner: <@{row['winner_id']}>\nRoblox: {a.get('roblox')}\n"
                f"Item: {a.get('item') or '—'}\nNotes: {a.get('notes') or '—'}\n\nReply `!paid {cid}` when done."
            )
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
        await ctx.reply(f"Claim {cid} marked paid."); await cleanup_message(ctx)
    @tasks.loop(minutes=10)
    async def _expiry(self):
        await self.pool.execute("UPDATE muta_giveaway_claims SET status='expired' WHERE status IN('pending','submitted') AND expires_at<NOW()")

async def setup_giveaway_claims(bot,pool):
    if not bot.get_cog("GiveawayClaims"): await bot.add_cog(GiveawayClaims(bot,pool))

# ================== DISCORD CLIENT ==================
intents=discord.Intents.default()
intents.message_content=True
intents.members=True
bot=commands.Bot(command_prefix="!",intents=intents)

# ================== HELP / COMMANDS EMBED ==================
def is_mod_or_admin(member:discord.Member)->bool:
    if member.guild_permissions.administrator: return True
    return any(r.id in HELP_MOD_ROLE_IDS for r in member.roles)

def build_commands_embed(author:discord.Member)->discord.Embed:
    mod=is_mod_or_admin(author)
    e=discord.Embed(title="📜 Commands",color=0x5865F2)
    e.add_field(
        name="Everyone",
        value="\n".join([
            "!ping",
            "!balance (aliases: !bal, !cashme, !mycash)",
            "!leaderboard",
            "!bugreport <desc>",
            "!countstatus",
            "!cash <4 words>  (claim a drop)"
        ]),
        inline=False
    )
    if mod:
        e.add_field(
            name="Mods/Admins",
            value="\n".join([
                "!send <text>",
                "!sendreact <text>",
                "!delete",
                "!addcash @user <amount> [reason]",
                "!removecash @user <amount> [reason]",
                "!doublecash on|off",
                "!gstart <dur|pipe>  (e.g. 1m | 1 | Title | Desc)",
                "!gend",
                "!greroll",
                "!countgoal <n>",
                "!countnext <n>",
                "!countreset",
                "!cashdrop",
                "!levelup @user <Rookie|Squad|Specialist|Operative|Legend>",
                "!paid <claim_id>"
            ]),
            inline=False
        )
    return e

# ================== UNIFIED MESSAGE HANDLER ==================
@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return

    c = msg.content.strip()

    # help shortcuts
    if c.lower() in ("!help","!commands"):
        await msg.channel.send(embed=build_commands_embed(msg.author))
        return await bot.process_commands(msg)

    # Counting channel enforcement
    if msg.channel.id == COUNT_CHANNEL_ID:
        state_path = "count_state.json"
        state = json.load(open(state_path)) if os.path.exists(state_path) else {"next":1,"goal":None}
        try: val=int(c)
        except: 
            try: await msg.delete()
            except: pass
            return
        if val!=state["next"]:
            try: await msg.delete()
            except: pass
            return
        state["next"]+=1
        json.dump(state,open(state_path,"w"))

    # W/F/L auto-reactions
    if msg.channel.id == WFL_CHANNEL_ID:
        cont=c.lower()
        added=False
        if "w" in cont: 
            await msg.add_reaction("🇼"); added=True
        if "f" in cont: 
            await msg.add_reaction("🇫"); added=True
        if "l" in cont: 
            await msg.add_reaction("🇱"); added=True

    # Earn-for-message
    if msg.channel.id in EARN_CHANNEL_IDS:
        uid=msg.author.id; now=utc_now()
        row=await _pool.fetchrow("SELECT last_earn_ts,today_earned FROM muta_users WHERE user_id=$1",uid)
        within_cd = row and row["last_earn_ts"] and (now-row["last_earn_ts"]).total_seconds() < EARN_COOLDOWN_SEC
        if not within_cd:
            length = len(msg.content)
            bonus = 100 if length>=100 else 80 if length>=50 else 50 if length>=10 else 0
            earn = (EARN_PER_TICK+bonus) * (2 if DOUBLE_CASH else 1)
            today = int(row["today_earned"]) if row and row["today_earnED".lower()] is not None else (int(row["today_earned"]) if row else 0)
            if today < DAILY_CAP:
                newtoday = min(today + earn, DAILY_CAP)
                await _pool.execute(
                    """INSERT INTO muta_users(user_id,cash,last_earn_ts,today_earned,activity_points) 
                       VALUES($1,$2,$3,$4,$5)
                       ON CONFLICT (user_id) DO UPDATE 
                       SET cash=muta_users.cash+EXCLUDED.cash,
                           last_earn_ts=$3,
                           today_earned=$4,
                           activity_points=muta_users.activity_points+EXCLUDED.activity_points""",
                    uid, earn, now, newtoday, earn
                )
                # Promotions
                ap_row=await _pool.fetchrow("SELECT activity_points FROM muta_users WHERE user_id=$1",uid)
                user=msg.guild.get_member(uid)
                if user and ap_row:
                    ap=int(ap_row["activity_points"] or 0)
                    to_add=[]
                    for role_id,thresh in ACTIVITY_THRESHOLDS:
                        if ap>=thresh and role_id not in [r.id for r in user.roles]:
                            r=msg.guild.get_role(role_id)
                            if r: to_add.append(r)
                    if to_add:
                        await user.add_roles(*to_add,reason="Activity level up")
                        ch=msg.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
                        if ch: await ch.send(f"{user.mention} reached the **{to_add[-1].name}** role! 🎉")

    # Cross-trade detector (skip excluded categories)
    if msg.guild and (not msg.channel.category or msg.channel.category.id not in CROSS_TRADE_EXCLUDED_CATEGORY_IDS):
        text = c.lower()
        for pat in TRADE_PATTERNS:
            if re.search(pat, text):
                uid=msg.author.id
                nowt=time()
                if uid in _last_trade_trigger and (nowt - _last_trade_trigger[uid]) < 120:
                    break
                _last_trade_trigger[uid]=nowt
                log=bot.get_channel(MOD_LOG_CHANNEL_ID)
                if log:
                    e=discord.Embed(
                        title="🚨 Cross-trade Detected",
                        description=f"User: {msg.author.mention}\nChannel: {msg.channel.mention}\nContent: {msg.content[:200]}",
                        color=0xFF0000
                    )
                    try: e.add_field(name="Jump", value=f"[Go to message]({msg.jump_url})", inline=False)
                    except: pass
                    await log.send(embed=e)
                break

    await bot.process_commands(msg)

# ================== PUBLIC COMMANDS ==================
@bot.command()
async def ping(ctx):
    await ctx.reply("pong 🏓")
    await cleanup_message(ctx)

@bot.command(name="balance", aliases=["bal","cashme","mycash"])
async def balance_cmd(ctx):
    bal=await get_balance(ctx.author.id)
    await ctx.reply(f"💰 {ctx.author.mention} balance: **{bal}**")
    await cleanup_message(ctx)

@bot.command()
async def leaderboard(ctx):
    rows=await _pool.fetch("SELECT user_id,cash FROM muta_users ORDER BY cash DESC LIMIT 10")
    if not rows:
        await ctx.send("No data yet.")
    else:
        desc="\n".join(f"**{i}.** <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows,start=1))
        await ctx.send(embed=discord.Embed(title="🏆 Top 10",description=desc,color=0xF1C40F))
    await cleanup_message(ctx)

@bot.command()
async def bugreport(ctx,*,desc:str):
    if len(desc)<5:
        await ctx.reply("Please include a description."); return await cleanup_message(ctx)
    ch=bot.get_channel(BUG_REVIEW_CHANNEL_ID)
    if not ch:
        await ctx.reply("Bug review channel not found."); return await cleanup_message(ctx)
    await ch.send(content=f"🐞 New bug from {ctx.author.mention}:\n> {desc}", view=None)
    await ctx.reply("Submitted for review!")
    await cleanup_message(ctx)

# ================== MOD/ADMIN COMMANDS ==================
def _is_modctx(ctx:commands.Context)->bool:
    return bool(is_mod_or_admin(ctx.author))

@bot.command()
async def send(ctx, *, text:str):
    if not _is_modctx(ctx): return
    await ctx.send(text)
    await cleanup_message(ctx)

@bot.command()
async def sendreact(ctx, *, text:str):
    if not _is_modctx(ctx): return
    msg = await ctx.send(text)
    for em in REACTION_ROLE_MAP.keys():
        try: await msg.add_reaction(em)
        except: pass
    # persist the tracked message for role handling
    try: json.dump({"msg":msg.id,"ch":ctx.channel.id}, open("reaction_msg.json","w"))
    except: pass
    await cleanup_message(ctx)

@bot.command()
async def delete(ctx):
    if not _is_modctx(ctx): return
    async for m in ctx.channel.history(limit=50):
        if m.author==bot.user:
            try: await m.delete()
            except: pass
            break
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def addcash(ctx,user:discord.Member,amount:int,*,reason="Adjustment"):
    if not _is_modctx(ctx): return
    await add_cash(user.id,amount)
    await ctx.send(f"➕ Added **{amount}** cash to {user.mention}. Reason: {reason}")
    await cleanup_message(ctx)

@bot.command()
async def removecash(ctx,user:discord.Member,amount:int,*,reason="Adjustment"):
    if not _is_modctx(ctx): return
    await add_cash(user.id,-amount)
    await ctx.send(f"➖ Removed **{amount}** cash from {user.mention}. Reason: {reason}")
    await cleanup_message(ctx)

@bot.command()
async def doublecash(ctx,switch:str):
    if not _is_modctx(ctx): return
    global DOUBLE_CASH; DOUBLE_CASH = (switch.lower()=="on")
    await ctx.send(f"Double cash is now {'ON' if DOUBLE_CASH else 'OFF'}.")
    await cleanup_message(ctx)

@bot.command()
async def levelup(ctx,user:discord.Member,role:str):
    if not _is_modctx(ctx): return
    roles={"rookie":ROLE_ROOKIE,"squad":ROLE_SQUAD,"specialist":ROLE_SPECIALIST,"operative":ROLE_OPERATIVE,"legend":ROLE_LEGEND}
    rid=roles.get(role.lower())
    if not rid:
        await ctx.send("Role must be one of: Rookie, Squad, Specialist, Operative, Legend")
        return await cleanup_message(ctx)
    r=ctx.guild.get_role(rid)
    if r:
        await user.add_roles(r,reason="Manual level up")
        ch=ctx.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
        if ch: await ch.send(f"{user.mention} reached the **{r.name}** role! 🎉")
    await cleanup_message(ctx)

# ================== REACTION ROLES (listeners) ==================
@bot.event
async def on_raw_reaction_add(p:discord.RawReactionActionEvent):
    if p.user_id==bot.user.id: return
    try:
        data=json.load(open("reaction_msg.json"))
    except:
        return
    if p.message_id==data.get("msg") and str(p.emoji) in REACTION_ROLE_MAP:
        g=bot.get_guild(GUILD_ID)
        if not g: return
        m=g.get_member(p.user_id); r=g.get_role(REACTION_ROLE_MAP[str(p.emoji)])
        if m and r and r not in m.roles:
            try: await m.add_roles(r)
            except: pass

@bot.event
async def on_raw_reaction_remove(p:discord.RawReactionActionEvent):
    try:
        data=json.load(open("reaction_msg.json"))
    except:
        return
    if p.message_id==data.get("msg") and str(p.emoji) in REACTION_ROLE_MAP:
        g=bot.get_guild(GUILD_ID)
        if not g: return
        m=g.get_member(p.user_id); r=g.get_role(REACTION_ROLE_MAP[str(p.emoji)])
        if m and r and r in m.roles:
            try: await m.remove_roles(r)
            except: pass

# ================== GIVEAWAYS ==================
GIVEAWAYS={}  # message_id -> data

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
        await i.response.send_message(f"{len(parts)} participants:\n"+(", ".join(f"<@{u}>" for u in parts) if parts else "None"),ephemeral=True)

async def schedule_giveaway_end(mid:int,ends:float):
    await asyncio.sleep(max(0,ends-time()))
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
            claims=bot.get_cog("GiveawayClaims"); 
            if not claims: await setup_giveaway_claims(bot,_pool); claims=bot.get_cog("GiveawayClaims")
            for w in winners:
                u=ch.guild.get_member(w)
                if u: await claims.start_claim_for_winner(ch.guild,u,gw["title"],sent,ch)
        else: await ch.send("No entries.")
    gw["ended"]=True; GIVEAWAYS[str(mid)]=gw

def _parse_duration_to_seconds(dtxt:str)->int:
    # supports like "1h", "30m", "0h 1m", "1d 2h", "90m" etc.
    total=0
    for tok in re.findall(r"(\d+)\s*([smhd])", dtxt.lower()):
        n=int(tok[0]); unit=tok[1]
        if unit=="s": total+=n
        elif unit=="m": total+=n*60
        elif unit=="h": total+=n*3600
        elif unit=="d": total+=n*86400
    return total if total>0 else 60  # default 60s

@bot.command()
async def gstart(ctx, *, args:str):
    if not _is_modctx(ctx): return
    # format: "<dur> | <winners> | <title> | <desc>"
    parts=[p.strip() for p in args.split("|")]
    if len(parts)<2:
        await ctx.send("Usage: `!gstart 1h | 1 | Title | Description`")
        return await cleanup_message(ctx)
    dur_txt=parts[0]
    winners_txt=parts[1]
    title=parts[2] if len(parts)>=3 else "Giveaway"
    desc=parts[3] if len(parts)>=4 else ""
    try:
        winners=int(winners_txt)
    except:
        await ctx.send("`<winners>` must be an integer.")
        return await cleanup_message(ctx)
    dur_s=_parse_duration_to_seconds(dur_txt)
    ends=time()+dur_s
    emb=discord.Embed(title=title,description=desc,color=0x5865F2)
    emb.add_field(name="Duration",value=dur_txt); emb.add_field(name="Winners",value=str(winners))
    msg=await ctx.send(embed=emb,view=GiveawayView(0))
    GIVEAWAYS[str(msg.id)]={"channel_id":ctx.channel.id,"ends_at":ends,"winners":winners,"title":title,"desc":desc,"participants":[],"ended":False}
    await msg.edit(view=GiveawayView(msg.id))
    asyncio.create_task(schedule_giveaway_end(msg.id,ends))
    await cleanup_message(ctx)

@bot.command()
async def gend(ctx):
    if not _is_modctx(ctx): return
    active=[int(mid) for mid,g in GIVEAWAYS.items() if not g.get("ended")]
    if not active: 
        await ctx.send("No active giveaways."); return await cleanup_message(ctx)
    await end_giveaway(max(active)); await ctx.send("✅ Giveaway ended.")
    await cleanup_message(ctx)

@bot.command()
async def greroll(ctx):
    if not _is_modctx(ctx): return
    any_g=[int(mid) for mid in GIVEAWAYS.keys()]
    if not any_g: 
        await ctx.send("No giveaways."); return await cleanup_message(ctx)
    await end_giveaway(max(any_g)); await ctx.send("✅ Rerolled.")
    await cleanup_message(ctx)

# ================== CASH DROPS ==================
_WORDS=["alpha","bravo","charlie","delta","eagle","frost","glow","hyper","ionic","jelly",
        "kyro","lumen","mango","nova","onyx","prism","quantum","raven","solar","tango",
        "ultra","vivid","wax","xeno","yodel","zen"]

def _four_words(): return " ".join(random.choice(_WORDS) for _ in range(DROP_WORD_COUNT))

@bot.command()
async def cashdrop(ctx, amount:int=DROP_AMOUNT):
    if not _is_modctx(ctx): return
    phrase=_four_words()
    ch=bot.get_channel(CASH_DROP_CHANNEL_ID) or ctx.channel
    emb=discord.Embed(
        title="[Cash] Cash drop!",
        description=f"Type `!cash {phrase}` to collect **{amount}** cash!",
        color=0x2ECC71
    )
    msg=await ch.send(embed=emb)
    await _pool.execute(
        "INSERT INTO muta_drops(channel_id,message_id,phrase,amount,created_at) VALUES($1,$2,$3,$4,NOW())",
        ch.id,msg.id,phrase.lower(),amount
    )
    await cleanup_message(ctx)

@bot.command(name="cash")
async def claim_cash(ctx,*,phrase:str=""):
    if not phrase: 
        await ctx.send(f"Usage: `!cash <{DROP_WORD_COUNT} words>`")
        return await cleanup_message(ctx)
    row=await _pool.fetchrow(
        "SELECT id,amount,channel_id,message_id FROM muta_drops WHERE phrase=$1 AND claimed_by IS NULL ORDER BY created_at DESC LIMIT 1",
        phrase.lower()
    )
    if not row: 
        await ctx.send("That drop was already claimed or not found.")
        return await cleanup_message(ctx)
    # claim atomically
    await _pool.execute("UPDATE muta_drops SET claimed_by=$1,claimed_at=NOW() WHERE id=$2 AND claimed_by IS NULL",ctx.author.id,row["id"])
    await add_cash(ctx.author.id,row["amount"])
    # delete the user's command
    try: await ctx.message.delete()
    except: pass
    # delete the original drop embed
    try:
        ch=bot.get_channel(row["channel_id"]); m=await ch.fetch_message(row["message_id"])
        await m.delete()
    except: pass
    # confirmation then auto-delete after 10s
    bal=await get_balance(ctx.author.id)
    confirm=await ctx.send(f"💸 {ctx.author.mention} claimed **{row['amount']}** cash! (bal: {bal})")
    try:
        await asyncio.sleep(10)
        await confirm.delete()
    except: pass

# ================== NEWCOMER PROMOTION ==================
@tasks.loop(minutes=10)
async def newcomer_promote_loop():
    g=bot.get_guild(GUILD_ID)
    if not g: return
    newcom=g.get_role(NEWCOMER_ROLE_ID); member_role=g.get_role(MEMBER_ROLE_ID)
    now=now_local()
    for m in g.members:
        if not m or m.bot: continue
        if newcom in m.roles and m.joined_at and (now-m.joined_at.astimezone(TZ))>=timedelta(days=3):
            try:
                await m.remove_roles(newcom,reason="3-day promotion")
                if member_role: await m.add_roles(member_role,reason="3-day promotion")
            except: pass

# ================== MONTHLY RESET ==================
@tasks.loop(minutes=1)
async def monthly_reset_loop():
    now=now_local()
    next_minute=now+timedelta(minutes=1)
    # 23:59 local & next minute is day 1
    if now.hour==23 and now.minute==59 and next_minute.day==1:
        rows=await _pool.fetch("SELECT user_id,cash FROM muta_users ORDER BY cash DESC LIMIT 10")
        g=bot.get_guild(GUILD_ID)
        if g:
            desc="\n".join(f"**{i}.** <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows,start=1)) if rows else ""
            for cid in [1414000088790863874,1411931034026643476,1411930067994411139,1411930091109224479,1411930689460240395,1414120740327788594]:
                ch=g.get_channel(cid)
                if not ch: continue
                try:
                    if desc:
                        await ch.send(embed=discord.Embed(title="🏁 Season ended — Final Top 10",description=desc,color=0xF39C12))
                    await ch.send("🧹 Balances reset. New season starts now — good luck!")
                except: pass
        await _pool.execute("UPDATE muta_users SET cash=0,today_earned=0")

# ================== YOUTUBE ANNOUNCEMENTS (POLLING FALLBACK) ==================
async def announce_youtube(video_id, title):
    g=bot.get_guild(GUILD_ID)
    ch=g.get_channel(YT_ANNOUNCE_CHANNEL_ID) if g else None
    role=g.get_role(YT_PING_ROLE_ID) if g else None
    if not ch or not role: return
    url=f"https://youtu.be/{video_id}"
    embed=discord.Embed(title=title, url=url, description=f"Mutapapa just released a new video called: {title}")
    embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    try:
        await ch.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
    except: pass

async def yt_poll_loop():
    await bot.wait_until_ready()
    last_file="yt_last_video.json"
    last_id=None
    if os.path.exists(last_file):
        try: last_id=json.load(open(last_file)).get("id")
        except: pass
    session=None
    try:
        session=aiohttp.ClientSession()
        while not bot.is_closed():
            try:
                async with session.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}", timeout=20) as r:
                    txt=await r.text()
                m=re.search(r"<yt:videoId>(.+?)</yt:videoId>", txt)
                t=re.search(r"<title>(.+?)</title>", txt)
                if m:
                    vid=m.group(1)
                    title=t.group(1) if t else "New Video"
                    if vid!=last_id:
                        await announce_youtube(vid, title)
                        last_id=vid
                        try: json.dump({"id":vid}, open(last_file,"w"))
                        except: pass
            except Exception as e:
                print("YT poll error:", e)
            await asyncio.sleep(300)
    finally:
        if session: await session.close()

# ================== X/TWITTER ANNOUNCEMENTS (POLLING FALLBACK) ==================
async def announce_tweet(tweet_id, text):
    g=bot.get_guild(GUILD_ID)
    ch=g.get_channel(X_ANNOUNCE_CHANNEL_ID) if g else None
    role=g.get_role(X_PING_ROLE_ID) if g else None
    if not ch or not role: return
    url=f"https://x.com/{X_USER}/status/{tweet_id}"
    embed=discord.Embed(title=(text or "New post on X"), url=url, description="Mutapapa just posted something on X (Formerly Twitter)! Click to check it out!")
    try:
        await ch.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
    except: pass

async def x_poll_loop():
    await bot.wait_until_ready()
    last_file="x_last_item.json"
    last_id=None
    if os.path.exists(last_file):
        try: last_id=json.load(open(last_file)).get("id")
        except: pass
    session=None
    try:
        session=aiohttp.ClientSession()
        while not bot.is_closed():
            try:
                async with session.get(X_RSS_URL, timeout=20) as r:
                    txt=await r.text()
                m=re.search(r"<link>https://x\.com/.+?/status/(\d+)</link>", txt)
                t=re.search(r"<title>(<!\[CDATA\[)?(.+?)(\]\]>)?</title>", txt)
                if m:
                    tid=m.group(1)
                    title=t.group(2).strip() if t else ""
                    if tid!=last_id:
                        await announce_tweet(tid, title)
                        last_id=tid
                        try: json.dump({"id":tid}, open(last_file,"w"))
                        except: pass
            except Exception as e:
                print("X poll error:", e)
            await asyncio.sleep(300)
    finally:
        if session: await session.close()

# ================== AIOHTTP MINI WEB (Render health + future WebSub) ==================
async def _health(request): return web.Response(text="ok")
async def _yt_webhook(request):
    # Minimal stub for PubSubHubbub verification/pings (not strictly needed with polling fallback)
    if request.method=="GET":
        # verification handshake
        hub_challenge=request.query.get("hub.challenge","")
        return web.Response(text=hub_challenge)
    elif request.method=="POST":
        # could parse atom; we rely on polling fallback anyway
        return web.Response(text="ok")
    return web.Response(status=405)

async def start_web_app():
    app = web.Application()
    app.router.add_get("/health", _health)
    app.router.add_get("/yt/webhook", _yt_webhook)
    app.router.add_post("/yt/webhook", _yt_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    port=int(os.getenv("PORT","0") or "0")
    if port<=0: port=8080  # default
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    print(f"Web server listening on :{port}")

# ================== READY ==================
@bot.event
async def on_ready():
    print(f"Ready as {bot.user}")
    await db_init()
    if not bot.get_cog("GiveawayClaims"): await setup_giveaway_claims(bot,_pool)
    if not newcomer_promote_loop.is_running(): newcomer_promote_loop.start()
    if not monthly_reset_loop.is_running(): monthly_reset_loop.start()
    # background tasks
    asyncio.create_task(yt_poll_loop())
    asyncio.create_task(x_poll_loop())
    asyncio.create_task(start_web_app())

# ================== RUN ==================
def main():
    token=os.getenv("DISCORD_TOKEN")
    if not token: raise RuntimeError("DISCORD_TOKEN missing")
    bot.run(token)

if __name__=="__main__": main()
