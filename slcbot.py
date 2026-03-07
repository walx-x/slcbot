import os
import discord
import psycopg2
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

AUTO_BAN_WARNINGS = 3
LOG_CHANNEL_ID = 1479152748598399046

XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161,
}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS xp (
    user_id BIGINT PRIMARY KEY,
    xp INT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    moderator_id BIGINT,
    reason TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ---------------- XP FUNCTIONS ----------------

def get_xp(user_id):
    cursor.execute("SELECT xp FROM xp WHERE user_id=%s",(user_id,))
    data = cursor.fetchone()
    return data[0] if data else 0

def set_xp(user_id,xp):
    cursor.execute("""
    INSERT INTO xp (user_id,xp)
    VALUES (%s,%s)
    ON CONFLICT (user_id)
    DO UPDATE SET xp=%s
    """,(user_id,xp,xp))
    conn.commit()

async def update_roles(member,xp):

    for req,role_id in XP_ROLES.items():

        role = member.guild.get_role(role_id)

        if not role:
            continue

        if xp >= req and role not in member.roles:

            await member.add_roles(role)

        elif xp < req and role in member.roles:

            await member.remove_roles(role)

# ---------------- WARN FUNCTIONS ----------------

def add_warning(user,mod,reason):

    cursor.execute("""
    INSERT INTO warnings (user_id,moderator_id,reason)
    VALUES (%s,%s,%s)
    """,(user,mod,reason))

    conn.commit()

def get_warnings(user):

    cursor.execute("""
    SELECT id,reason,timestamp FROM warnings
    WHERE user_id=%s
    """,(user,))

    return cursor.fetchall()

# ---------------- EVENTS ----------------

@bot.event
async def on_ready():

    await bot.tree.sync()

    print(f"Bot online: {bot.user}")

@bot.event
async def on_member_join(member):

    embed = discord.Embed(
        title=f"👋 Welcome {member.name}",
        description="Follow these steps to join SLCartel",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="1️⃣ Verify",
        value="Go to **✅・verify** and verify with RoVer",
        inline=False
    )

    embed.add_field(
        name="2️⃣ Become Member",
        value="Go to **👥・become-member**",
        inline=False
    )

    embed.add_field(
        name="3️⃣ Send Screenshot",
        value="Send screenshot in **🎫・create-ticket**",
        inline=False
    )

    try:
        await member.send(embed=embed)
    except:
        pass

# ---------------- XP COMMANDS ----------------

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_add")
async def xp_add(interaction:discord.Interaction,user:discord.Member,amount:int):

    xp = get_xp(user.id)+amount

    set_xp(user.id,xp)

    await update_roles(user,xp)

    await interaction.response.send_message(
        f"Added {amount} XP to {user.mention} (Total {xp})"
    )

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_remove")
async def xp_remove(interaction:discord.Interaction,user:discord.Member,amount:int):

    xp=max(0,get_xp(user.id)-amount)

    set_xp(user.id,xp)

    await update_roles(user,xp)

    await interaction.response.send_message(
        f"Removed {amount} XP from {user.mention} (Total {xp})"
    )

@bot.tree.command(name="xp_check")
async def xp_check(interaction:discord.Interaction,user:discord.Member=None):

    user=user or interaction.user

    xp=get_xp(user.id)

    embed=discord.Embed(title=f"{user.name} XP")

    embed.add_field(name="XP",value=xp)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="xp_leaderboard")
async def leaderboard(interaction:discord.Interaction):

    cursor.execute("SELECT user_id,xp FROM xp ORDER BY xp DESC LIMIT 10")

    data=cursor.fetchall()

    embed=discord.Embed(title="XP Leaderboard")

    for i,(uid,xp) in enumerate(data,1):

        member=interaction.guild.get_member(uid)

        name=member.name if member else uid

        embed.add_field(name=f"{i}. {name}",value=f"{xp} XP",inline=False)

    await interaction.response.send_message(embed=embed)

# ---------------- WARN ----------------

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn")
async def warn(interaction:discord.Interaction,user:discord.Member,reason:str="No reason"):

    await interaction.response.defer()

    add_warning(user.id,interaction.user.id,reason)

    warns=get_warnings(user.id)

    embed=discord.Embed(title="⚠️ Warning",color=discord.Color.orange())

    embed.add_field(name="User",value=user.mention)

    embed.add_field(name="Moderator",value=interaction.user.mention)

    embed.add_field(name="Reason",value=reason,inline=False)

    embed.add_field(name="Total warnings",value=len(warns))

    log=interaction.guild.get_channel(LOG_CHANNEL_ID)

    if log:

        await log.send(embed=embed)

    if len(warnings) >= AUTO_BAN_WARNINGS:
    await user.ban(reason="Too many warnings")
    await send_log(interaction.guild, f"🔨 {user} auto-banned (warnings limit reached)")

    await interaction.followup.send(
        f"⚠️ {user.mention} has been **warned**.\n"
        f"📊 Total warnings: **{len(warnings)}**\n"
        f"🚫 User has been **auto-banned** for reaching the limit."
    )

else:
    await interaction.followup.send(
        f"⚠️ {user.mention} has been **warned**.\n"
        f"📊 Total warnings: **{len(warnings)}**"
    )

# ---------------- WARNINGS ALL ----------------

@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="warnings_all")
async def warnings_all(interaction:discord.Interaction):

    cursor.execute("""
    SELECT user_id,moderator_id,reason,timestamp
    FROM warnings
    ORDER BY timestamp DESC
    """)

    data=cursor.fetchall()

    if not data:

        await interaction.response.send_message("No warnings")

        return

    text=""

    for uid,mid,reason,time in data:

        user=interaction.guild.get_member(uid)

        mod=interaction.guild.get_member(mid)

        uname=user.name if user else uid

        mname=mod.name if mod else mid

        text+=f"{uname} | {mname} | {reason} | {time}\n"

    await interaction.response.send_message(text[:2000])

# ---------------- MODERATION ----------------

@bot.tree.command(name="ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction:discord.Interaction,user:discord.Member):

    await user.ban()

    await interaction.response.send_message(
        f"{user.mention} banned"
    )

@bot.tree.command(name="kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction:discord.Interaction,user:discord.Member):

    await user.kick()

    await interaction.response.send_message(
        f"{user.mention} kicked"
    )

@bot.tree.command(name="mute")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction:discord.Interaction,user:discord.Member,minutes:int):

    await user.timeout(timedelta(minutes=minutes))

    await interaction.response.send_message(
        f"{user.mention} muted {minutes} minutes"
    )

@bot.tree.command(name="unmute")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction:discord.Interaction,user:discord.Member):

    await user.timeout(None)

    await interaction.response.send_message(
        f"{user.mention} unmuted"
    )

# ---------------- CLEAR ----------------

@bot.tree.command(name="clear")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction:discord.Interaction,amount:int):

    deleted=await interaction.channel.purge(limit=amount)

    await interaction.response.send_message(
        f"Deleted {len(deleted)} messages",
        ephemeral=True
    )

# ---------------- START ----------------

bot.run(TOKEN)

