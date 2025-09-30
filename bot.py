# bot.py
import os, re, json, random, asyncio, aiohttp
from time import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import discord
from discord.ext import commands, tasks
from discord.ui import View, button

# ================== CORE CONFIG ==================
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
TZ = ZoneInfo("America/Edmonton")
def utc_now(): return datetime.now(timezone.utc)
def now_local(): return datetime.now(TZ)

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
        try: await winner.send(f"Congrats {winner.mention}! You won **{title}** 🎉\nType `claim` or press button within 24h.",view=ClaimStartView(self,cid))
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
        await ctx.reply(f"Claim {cid} marked paid."); await cleanup_message(ctx)
    @tasks.loop(minutes=10)
    async def _expiry(self):
        await self.pool.execute("UPDATE muta_giveaway_claims SET status='expired' WHERE status IN('pending','submitted') AND expires_at<NOW()")

async def setup_giveaway_claims(bot,pool):
    if not bot.get_cog("GiveawayClaims"): await bot.add_cog(GiveawayClaims(bot,pool))

# ================== IDS & CONFIG ==================
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
EARN_CHANNEL_IDS=[1411930638260502638,1411486271464935456,1413297073348018299,1411935203953217566,1411435784250331288,1412144563144888452,1411931216608755782,1414000975680897128,1411433941403177054,1411931171671117854,1411946767414591538,1413999346592256050,1414001588091093052]
EARN_COOLDOWN_SEC=180; EARN_PER_TICK=200; DAILY_CAP=2000; DOUBLE_CASH=False
DROP_AMOUNT=225; DROP_WORD_COUNT=4
BUG_REWARD_AMOUNT=350; BUG_REWARD_LIMIT_PER_MONTH=2
ROLE_ROOKIE=1414817524557549629; ROLE_SQUAD=1414818303028891731; ROLE_SPECIALIST=1414818845541138493; ROLE_OPERATIVE=1414819588448718880; ROLE_LEGEND=1414819897602474057
ACTIVITY_THRESHOLDS=[(ROLE_ROOKIE,5000),(ROLE_SQUAD,25000),(ROLE_SPECIALIST,75000),(ROLE_OPERATIVE,180000),(ROLE_LEGEND,400000)]
HELP_MOD_ROLE_IDS={1413663966349234320,1411940485005578322,1413991410901713088}
TRADE_PATTERNS=[r"paypal",r"cashapp",r"venmo",r"crypto",r"buy.*robux",r"sell.*robux"]
last_trigger={}

# ================== DB INIT ==================
DB_URL=os.getenv("SUPABASE_DB_URL","").strip(); _pool=None
async def db_init():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=DB_URL, min_size=1, max_size=5,
        statement_cache_size=0   # fix PgBouncer
    )
    async with _pool.acquire() as con:
        await con.execute("CREATE TABLE IF NOT EXISTS muta_meta(key TEXT PRIMARY KEY,value TEXT)")
        await con.execute("CREATE TABLE IF NOT EXISTS muta_users(user_id BIGINT PRIMARY KEY,cash BIGINT DEFAULT 0,last_earn_ts TIMESTAMPTZ,today_earned BIGINT DEFAULT 0,bug_rewards_this_month INT DEFAULT 0,activity_points BIGINT DEFAULT 0)")
        await con.execute("CREATE TABLE IF NOT EXISTS muta_drops(id BIGSERIAL PRIMARY KEY,channel_id BIGINT,message_id BIGINT UNIQUE,phrase TEXT,amount INT,claimed_by BIGINT,claimed_at TIMESTAMPTZ,created_at TIMESTAMPTZ DEFAULT NOW())")
        await con.execute("CREATE TABLE IF NOT EXISTS muta_giveaway_claims(id BIGSERIAL PRIMARY KEY,guild_id BIGINT,giveaway_title TEXT,winner_id BIGINT,status TEXT DEFAULT 'pending',created_at TIMESTAMPTZ DEFAULT NOW(),expires_at TIMESTAMPTZ,answers JSONB DEFAULT '{}'::jsonb)")

# ================== DISCORD CLIENT ==================
intents=discord.Intents.default(); intents.message_content=True; intents.members=True
bot=commands.Bot(command_prefix="!",intents=intents)

# ================== ECONOMY ==================
async def add_cash(user_id:int,amount:int,reason:str=None,activity_pts:int=0):
    await _pool.execute(
        """INSERT INTO muta_users(user_id,cash,activity_points) 
           VALUES($1,$2,$3) 
           ON CONFLICT (user_id) DO UPDATE 
           SET cash=muta_users.cash+EXCLUDED.cash,
               activity_points=muta_users.activity_points+EXCLUDED.activity_points""",
        user_id,amount,activity_pts)

async def get_balance(user_id:int):
    row=await _pool.fetchrow("SELECT cash FROM muta_users WHERE user_id=$1",user_id)
    return row["cash"] if row else 0

# ================== UNIFIED ON_MESSAGE ==================
@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot: return

    # Counting channel
    if msg.channel.id == COUNT_CHANNEL_ID:
        state = json.load(open("count_state.json")) if os.path.exists("count_state.json") else {"next":1,"goal":None}
        try: val=int(msg.content.strip())
        except: return await msg.delete()
        if val!=state["next"]: return await msg.delete()
        state["next"]+=1; json.dump(state,open("count_state.json","w"))

    # W/F/L reactions
    elif msg.channel.id == WFL_CHANNEL_ID:
        cont=msg.content.lower()
        if "w" in cont: await msg.add_reaction("🇼")
        if "f" in cont: await msg.add_reaction("🇫")
        if "l" in cont: await msg.add_reaction("🇱")

    # Earn system
    if msg.channel.id in EARN_CHANNEL_IDS:
        uid=msg.author.id; now=utc_now()
        row=await _pool.fetchrow("SELECT last_earn_ts,today_earned FROM muta_users WHERE user_id=$1",uid)
        if not (row and row["last_earn_ts"] and (now-row["last_earn_ts"]).total_seconds()<EARN_COOLDOWN_SEC):
            length_bonus=100 if len(msg.content)>=100 else 80 if len(msg.content)>=50 else 50 if len(msg.content)>=10 else 0
            earn=EARN_PER_TICK+length_bonus
            if DOUBLE_CASH: earn*=2
            today=row["today_earned"] if row else 0
            if today<DAILY_CAP:
                newtoday=min(today+earn,DAILY_CAP)
                await _pool.execute(
                    """INSERT INTO muta_users(user_id,cash,last_earn_ts,today_earned,activity_points) 
                       VALUES($1,$2,$3,$4,$5)
                       ON CONFLICT (user_id) DO UPDATE 
                       SET cash=muta_users.cash+EXCLUDED.cash,
                           last_earn_ts=$3,
                           today_earned=$4,
                           activity_points=muta_users.activity_points+EXCLUDED.activity_points""",
                    uid,earn,now,newtoday,earn)
                row=await _pool.fetchrow("SELECT activity_points FROM muta_users WHERE user_id=$1",uid)
                user=msg.guild.get_member(uid)
                for role_id,thresh in ACTIVITY_THRESHOLDS:
                    if row and row["activity_points"]>=thresh and role_id not in [r.id for r in user.roles]:
                        await user.add_roles(msg.guild.get_role(role_id))
                        ch=msg.guild.get_channel(LEVEL_UP_ANNOUNCE_CHANNEL_ID)
                        await ch.send(f"**{user.mention}** reached the **{msg.guild.get_role(role_id).name}** role!")

    # Cross-trade detector
    if msg.guild and msg.channel.category and msg.channel.category.id not in CROSS_TRADE_EXCLUDED_CATEGORY_IDS:
        for pat in TRADE_PATTERNS:
            if re.search(pat,msg.content.lower()):
                uid=msg.author.id; now=time()
                if uid in last_trigger and now-last_trigger[uid]<120: break
                last_trigger[uid]=now
                ch=bot.get_channel(MOD_LOG_CHANNEL_ID)
                await ch.send(f"🚨 Cross-trade detected from {msg.author.mention} in {msg.channel.mention}\nContent: {msg.content[:100]}")
                break

    await bot.process_commands(msg)

# ================== COMMANDS ==================
@bot.command()
async def ping(ctx): await ctx.reply("pong 🏓"); await cleanup_message(ctx)

@bot.command(aliases=["balance","bal","cashme","mycash"])
async def cash(ctx):
    bal=await get_balance(ctx.author.id)
    await ctx.reply(f"{ctx.author.mention}, you have {bal} cash."); await cleanup_message(ctx)

@bot.command()
async def leaderboard(ctx):
    rows=await _pool.fetch("SELECT user_id,cash FROM muta_users ORDER BY cash DESC LIMIT 10")
    text="**Leaderboard**\n"+"\n".join([f"{i+1}. <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows)])
    await ctx.send(text); await cleanup_message(ctx)

@bot.command()
@commands.has_permissions(administrator=True)
async def addcash(ctx,member:discord.Member,amount:int,*reason):
    await add_cash(member.id,amount,reason=" ".join(reason))
    await ctx.reply(f"Added {amount} to {member.mention}"); await cleanup_message(ctx)

@bot.command(aliases=["balance","bal","cashme"])
async def mycash(ctx):
    bal = await get_balance(ctx.author.id)
    await ctx.reply(f"{ctx.author.mention}, you have {bal} cash.")
    await cleanup_message(ctx)

@bot.command()
@commands.has_permissions(administrator=True)
async def doublecash(ctx,opt:str):
    global DOUBLE_CASH; DOUBLE_CASH=(opt.lower()=="on")
    await ctx.reply(f"Double cash {'enabled' if DOUBLE_CASH else 'disabled'}"); await cleanup_message(ctx)

# Cash drops
@bot.command()
@commands.has_permissions(administrator=True)
async def cashdrop(ctx):
    words=["apple","banana","cherry","delta","echo","foxtrot","golf","hotel","india","juliet"]
    phrase=" ".join(random.sample(words,DROP_WORD_COUNT))
    ch=bot.get_channel(CASH_DROP_CHANNEL_ID)
    m=await ch.send(f"💰 Cash drop! Type `!cash {phrase}` to claim {DROP_AMOUNT} cash!")
    await _pool.execute("INSERT INTO muta_drops(channel_id,message_id,phrase,amount) VALUES($1,$2,$3,$4)",ch.id,m.id,phrase,DROP_AMOUNT)
    await cleanup_message(ctx)

@bot.command(name="cash")
async def claim(ctx,*words):
    phrase=" ".join(words)
    row=await _pool.fetchrow("SELECT * FROM muta_drops WHERE phrase=$1 AND claimed_by IS NULL ORDER BY created_at DESC LIMIT 1",phrase)
    if not row: return
    await add_cash(ctx.author.id,row["amount"])
    await _pool.execute("UPDATE muta_drops SET claimed_by=$1,claimed_at=NOW() WHERE id=$2",ctx.author.id,row["id"])
    try: await ctx.message.delete()
    except: pass
    try: ch=bot.get_channel(row["channel_id"]); m=await ch.fetch_message(row["message_id"]); await m.delete()
    except: pass
    confirm=await ctx.send(f"{ctx.author.mention} claimed {row['amount']} cash! Balance: {await get_balance(ctx.author.id)}")
    await asyncio.sleep(10); await confirm.delete()

# Bug reports
class BugView(View):
    def __init__(self,author_id:int): super().__init__(timeout=None); self.author_id=author_id
    @button(label="Approve",style=discord.ButtonStyle.success)
    async def approve(self,i,_):
        uid=self.author_id
        row=await _pool.fetchrow("SELECT bug_rewards_this_month FROM muta_users WHERE user_id=$1",uid)
        if row and row["bug_rewards_this_month"]>=BUG_REWARD_LIMIT_PER_MONTH:
            return await i.response.send_message("Limit reached this month.",ephemeral=True)
        await add_cash(uid,BUG_REWARD_AMOUNT)
        await _pool.execute("UPDATE muta_users SET bug_rewards_this_month=COALESCE(bug_rewards_this_month,0)+1 WHERE user_id=$1",uid)
        await i.response.send_message("Approved ✅",ephemeral=True)
    @button(label="Reject",style=discord.ButtonStyle.danger)
    async def reject(self,i,_): await i.response.send_message("Rejected ❌",ephemeral=True)

@bot.command()
async def bugreport(ctx,*,desc):
    ch=bot.get_channel(BUG_REVIEW_CHANNEL_ID)
    await ch.send(f"🐞 Bug from {ctx.author.mention}: {desc}",view=BugView(ctx.author.id))
    await ctx.reply("Sent bug report!"); await cleanup_message(ctx)

# Reaction roles
@bot.command()
@commands.has_permissions(administrator=True)
async def sendreact(ctx,*,text):
    ch=bot.get_channel(ctx.channel.id)
    m=await ch.send(text)
    for e in REACTION_ROLE_MAP: await m.add_reaction(e)
    json.dump({"msg":m.id,"ch":ch.id},open("reaction_msg.json","w"))
    await cleanup_message(ctx)

@bot.event
async def on_raw_reaction_add(p):
    if p.user_id==bot.user.id: return
    data=json.load(open("reaction_msg.json"))
    if p.message_id==data["msg"] and str(p.emoji) in REACTION_ROLE_MAP:
        g=bot.get_guild(GUILD_ID); m=g.get_member(p.user_id)
        await m.add_roles(g.get_role(REACTION_ROLE_MAP[str(p.emoji)]))

@bot.event
async def on_raw_reaction_remove(p):
    data=json.load(open("reaction_msg.json"))
    if p.message_id==data["msg"] and str(p.emoji) in REACTION_ROLE_MAP:
        g=bot.get_guild(GUILD_ID); m=g.get_member(p.user_id)
        await m.remove_roles(g.get_role(REACTION_ROLE_MAP[str(p.emoji)]))

# Newcomer promotion
@tasks.loop(hours=1)
async def newcomer_promote_loop():
    g=bot.get_guild(GUILD_ID)
    for m in g.members:
        if NEWCOMER_ROLE_ID in [r.id for r in m.roles]:
            if (utc_now()-m.joined_at).days>=3:
                await m.remove_roles(g.get_role(NEWCOMER_ROLE_ID))
                await m.add_roles(g.get_role(MEMBER_ROLE_ID))

# Monthly reset
@tasks.loop(hours=24)
async def monthly_reset_loop():
    now=now_local()
    if now.day!=1: return
    rows=await _pool.fetch("SELECT user_id,cash FROM muta_users ORDER BY cash DESC LIMIT 10")
    text="**Final Top 10**\n"+"\n".join([f"{i+1}. <@{r['user_id']}> — {r['cash']}" for i,r in enumerate(rows)])
    for cid in [1414000088790863874,1411931034026643476,1411930067994411139,1411930091109224479,1411930689460240395,1414120740327788594]:
        try: await bot.get_channel(cid).send(text)
        except: pass
    await _pool.execute("UPDATE muta_users SET cash=0,today_earned=0")

    # ================== YOUTUBE ANNOUNCEMENTS ==================
YT_CHANNEL_ID = "UCSLxLMfxnFRxyhNOZMy4i9w"
YT_SECRET = "mutapapa-youtube"
BANNER_URL = os.getenv("BANNER_URL","")

async def announce_youtube(video_id, title):
    ch = bot.get_channel(YT_ANNOUNCE_CHANNEL_ID)
    role = bot.get_guild(GUILD_ID).get_role(YT_PING_ROLE_ID)
    url = f"https://youtu.be/{video_id}"
    embed = discord.Embed(title=title, url=url, description=f"{role.mention} Mutapapa just released a new video called: {title} Click to watch it!")
    embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    await ch.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

async def yt_poll_loop():
    await bot.wait_until_ready()
    last_file = "yt_last_video.json"
    last_id = json.load(open(last_file))["id"] if os.path.exists(last_file) else None
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}") as r:
                    txt = await r.text()
            m = re.search(r"<yt:videoId>(.+?)</yt:videoId>", txt)
            if m:
                vid = m.group(1)
                if vid != last_id:
                    title = re.search(r"<title>(.+?)</title>", txt).group(1)
                    await announce_youtube(vid, title)
                    last_id = vid
                    json.dump({"id":vid},open(last_file,"w"))
        except Exception as e: print("YT poll error",e)
        await asyncio.sleep(300)

bot.loop.create_task(yt_poll_loop())

# ================== TWITTER/X ANNOUNCEMENTS ==================
X_USER = "Real_Mutapapa"
X_RSS_URL = os.getenv("X_RSS_URL", f"https://nitter.net/{X_USER}/rss")

async def announce_tweet(tweet_id, text):
    ch = bot.get_channel(X_ANNOUNCE_CHANNEL_ID)
    role = bot.get_guild(GUILD_ID).get_role(X_PING_ROLE_ID)
    url = f"https://x.com/{X_USER}/status/{tweet_id}"
    embed = discord.Embed(title=text or "New post on X", url=url, description="Mutapapa just posted something on X (Formerly Twitter)! Click to check it out!")
    await ch.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

async def x_poll_loop():
    await bot.wait_until_ready()
    last_file = "x_last_item.json"
    last_id = json.load(open(last_file))["id"] if os.path.exists(last_file) else None
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(X_RSS_URL) as r:
                    txt = await r.text()
            m = re.search(r"<link>https://x.com/.+?/status/(\d+)</link>", txt)
            if m:
                tid = m.group(1)
                if tid != last_id:
                    text = re.search(r"<title>(.+?)</title>", txt).group(1)
                    await announce_tweet(tid, text)
                    last_id = tid
                    json.dump({"id":tid},open(last_file,"w"))
        except Exception as e: print("X poll error",e)
        await asyncio.sleep(300)

bot.loop.create_task(x_poll_loop())

# ================== READY ==================
@bot.event
async def on_ready():
    print(f"Ready as {bot.user}")
    await db_init()
    if not newcomer_promote_loop.is_running(): newcomer_promote_loop.start()
    if not monthly_reset_loop.is_running(): monthly_reset_loop.start()
    if not bot.get_cog("GiveawayClaims"): await setup_giveaway_claims(bot,_pool)

# ================== RUN ==================
def main():
    t=os.getenv("DISCORD_TOKEN")
    if not t: raise RuntimeError("DISCORD_TOKEN missing")
    bot.run(t)

if __name__=="__main__": main()
