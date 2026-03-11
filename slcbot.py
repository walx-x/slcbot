import os
import discord
import psycopg2
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

TOKEN=os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL=os.getenv("DATABASE_URL")

AUTO_BAN_WARNINGS=3
LOG_CHANNEL_ID=1479152748598399046

XP_ROLES={
100:1479870836889620580,
300:1479871300662202489,
600:1479871518627463178
}

intents=discord.Intents.all()
bot=commands.Bot(command_prefix="!",intents=intents)

# ---------------- DATABASE ----------------

conn=psycopg2.connect(DATABASE_URL)
cursor=conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS xp(
user_id BIGINT PRIMARY KEY,
xp INT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings(
id SERIAL PRIMARY KEY,
user_id BIGINT,
moderator_id BIGINT,
reason TEXT,
timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ---------------- MODLOG ----------------

async def send_modlog(guild,title,fields):

    if not LOG_CHANNEL_ID:
        return

    channel=guild.get_channel(LOG_CHANNEL_ID)

    if not channel:
        return

    embed=discord.Embed(title=title,color=discord.Color.orange())

    for name,value in fields:
        embed.add_field(name=name,value=value,inline=False)

    await channel.send(embed=embed)

# ---------------- XP FUNCTIONS ----------------

def get_xp(user_id):

    cursor.execute("SELECT xp FROM xp WHERE user_id=%s",(user_id,))
    data=cursor.fetchone()

    return data[0] if data else 0

def set_xp(user_id,xp):

    cursor.execute("""
    INSERT INTO xp(user_id,xp)
    VALUES(%s,%s)
    ON CONFLICT(user_id)
    DO UPDATE SET xp=%s
    """,(user_id,xp,xp))

    conn.commit()

async def update_roles(member,xp):

    for req,role_id in XP_ROLES.items():

        role=member.guild.get_role(role_id)

        if not role:
            continue

        if xp>=req and role not in member.roles:

            await member.add_roles(role)

        elif xp<req and role in member.roles:

            await member.remove_roles(role)

# ---------------- WARN FUNCTIONS ----------------

def add_warning(user,mod,reason):

    cursor.execute("""
    INSERT INTO warnings(user_id,moderator_id,reason)
    VALUES(%s,%s,%s)
    """,(user,mod,reason))

    conn.commit()

def get_warnings(user):

    cursor.execute("""
    SELECT id,moderator_id,reason,timestamp
    FROM warnings
    WHERE user_id=%s
    """,(user,))

    return cursor.fetchall()

def clear_warnings(user):

    cursor.execute("""
    DELETE FROM warnings
    WHERE user_id=%s
    """,(user,))

    conn.commit()

async def send_warn_dm(user,reason,moderator):

    try:

        embed=discord.Embed(
        title="⚠️ You received a warning",
        color=discord.Color.orange()
        )

        embed.add_field(name="Reason",value=reason)
        embed.add_field(name="Moderator",value=str(moderator))

        await user.send(embed=embed)

    except:
        pass

# ---------------- EVENTS ----------------

@bot.event
async def on_ready():

    await bot.tree.sync()

    print(f"Bot online: {bot.user}")

@bot.event
async def on_member_join(member):

    embed=discord.Embed(
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

    xp=get_xp(user.id)+amount
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
async def xp_check(interaction: discord.Interaction, user: discord.Member=None):

    user = user or interaction.user
    xp = get_xp(user.id)

    sorted_roles = sorted(XP_ROLES.items())

    current_rank = "🎖️ Unranked"
    next_rank = None
    next_xp = None
    current_req = 0

    for req, role_id in sorted_roles:

        role = interaction.guild.get_role(role_id)

        if xp >= req:
            current_rank = f"🏅 {role.name}"
            current_req = req
        else:
            next_rank = role.name
            next_xp = req
            break

    if next_xp:

        progress = (xp - current_req) / (next_xp - current_req)
        progress = max(0, min(progress, 1))

        filled = int(progress * 20)

        bar = "▰" * filled + "▱" * (20 - filled)

        percent = round(progress * 100, 1)

    else:

        bar = "▰" * 20
        percent = 100

    embed = discord.Embed(
        title=f"⭐ {user.display_name}'s XP Profile",
        color=discord.Color.blue()
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="🏅 Rank", value=current_rank)
    embed.add_field(name="✨ XP", value=f"{xp} XP")

    embed.add_field(
        name="📊 Progress",
        value=f"{bar}\n{percent}%"
    )

    if next_rank:
        embed.add_field(
            name="Next Rank",
            value=f"{next_rank} ({next_xp} XP)",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="xp_leaderboard")
async def xp_leaderboard(interaction:discord.Interaction):

    cursor.execute("SELECT user_id,xp FROM xp ORDER BY xp DESC LIMIT 10")
    rows=cursor.fetchall()

    embed=discord.Embed(
    title="🏆 SLCartel XP Leaderboard",
    color=discord.Color.gold()
    )

    medals=["🥇","🥈","🥉"]

    for idx,(uid,xp) in enumerate(rows,1):

        member=interaction.guild.get_member(uid)
        name=member.name if member else uid

        prefix=medals[idx-1] if idx<=3 else f"#{idx}"

        embed.add_field(
        name=f"{prefix} {name}",
        value=f"✨ {xp} XP",
        inline=False
        )

    await interaction.response.send_message(embed=embed)

# ---------------- WARN COMMANDS ----------------

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn")
async def warn(interaction:discord.Interaction,user:discord.Member,reason:str="No reason"):

    await interaction.response.defer()

    add_warning(user.id,interaction.user.id,reason)

    warnings=get_warnings(user.id)

    await send_warn_dm(user,reason,interaction.user)

    await send_modlog(
    interaction.guild,
    "⚠️ Warning",
    [
    ("User",user.mention),
    ("Moderator",interaction.user.mention),
    ("Reason",reason),
    ("Total warnings",str(len(warnings)))
    ]
    )

    if len(warnings)>=AUTO_BAN_WARNINGS:

        await user.ban(reason="Too many warnings")

        await interaction.followup.send(
        f"{user.mention} warned and auto banned"
        )

    else:

        await interaction.followup.send(
        f"{user.mention} warned ({len(warnings)} total)"
        )

# ---------------- WARNINGS USER ----------------

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings")
async def warnings(interaction:discord.Interaction,user:discord.Member):

    data=get_warnings(user.id)

    if not data:

        await interaction.response.send_message(
        f"{user.mention} has no warnings"
        )

        return

    embed=discord.Embed(
    title=f"⚠️ Warnings for {user}",
    color=discord.Color.orange()
    )

    for wid,mod,reason,time in data:

        moderator=interaction.guild.get_member(mod)
        mod_name=moderator.name if moderator else mod

        embed.add_field(
        name=f"Warning {wid}",
        value=f"Moderator: {mod_name}\nReason: {reason}",
        inline=False
        )

    await interaction.response.send_message(embed=embed)

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

    embed=discord.Embed(
    title="📜 All Warnings",
    color=discord.Color.orange()
    )

    for uid,mid,reason,time in data:

        user=interaction.guild.get_member(uid)
        mod=interaction.guild.get_member(mid)

        uname=user.name if user else uid
        mname=mod.name if mod else mid

        embed.add_field(
        name=uname,
        value=f"Moderator: {mname}\nReason: {reason}",
        inline=False
        )

    await interaction.response.send_message(embed=embed)

# ---------------- CLEAR WARNINGS ----------------

@bot.tree.command(name="clear_warnings")
@app_commands.checks.has_permissions(administrator=True)
async def clear_user_warnings(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str
):

    clear_warnings(user.id)

    await send_modlog(
        interaction.guild,
        "🗑️ Warnings Cleared",
        [
            ("User", user.mention),
            ("Moderator", interaction.user.mention),
            ("Reason", reason)
        ]
    )

    await interaction.response.send_message(
        f"Warnings cleared for {user.mention}\nReason: {reason}"
    )

# ---------------- MODERATION ----------------

@bot.tree.command(name="ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str):

    try:

        embed = discord.Embed(
            title="🔨 You have been banned",
            color=discord.Color.red()
        )

        embed.add_field(name="Server", value=interaction.guild.name)
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason)

        await user.send(embed=embed)

    except:
        pass

    await user.ban(reason=reason)

    await send_modlog(
        interaction.guild,
        "🔨 Ban",
        [
            ("User", user.mention),
            ("Moderator", interaction.user.mention),
            ("Reason", reason)
        ]
    )

    await interaction.response.send_message(
        f"{user.mention} banned\nReason: {reason}"
    )

@bot.tree.command(name="kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str):

    try:

        embed = discord.Embed(
            title="👢 You have been kicked",
            color=discord.Color.orange()
        )

        embed.add_field(name="Server", value=interaction.guild.name)
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason)

        await user.send(embed=embed)

    except:
        pass

    await user.kick(reason=reason)

    await send_modlog(
        interaction.guild,
        "👢 Kick",
        [
            ("User", user.mention),
            ("Moderator", interaction.user.mention),
            ("Reason", reason)
        ]
    )

    await interaction.response.send_message(
        f"{user.mention} kicked\nReason: {reason}"
    )
@bot.tree.command(name="mute")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction:discord.Interaction,user:discord.Member,minutes:int):

    await user.timeout(timedelta(minutes=minutes))

    await send_modlog(
    interaction.guild,
    "🔇 Mute",
    [
    ("User",user.mention),
    ("Moderator",interaction.user.mention),
    ("Duration",f"{minutes} minutes")
    ]
    )

    await interaction.response.send_message(
    f"{user.mention} muted {minutes} minutes"
    )

@bot.tree.command(name="unmute")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction:discord.Interaction,user:discord.Member):

    await user.timeout(None)

    await send_modlog(
    interaction.guild,
    "🔊 Unmute",
    [
    ("User",user.mention),
    ("Moderator",interaction.user.mention)
    ]
    )

    await interaction.response.send_message(
    f"{user.mention} unmuted"
    )

# ---------------- CLEAR ----------------

@bot.tree.command(name="clear")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction:discord.Interaction,amount:int):

    deleted=await interaction.channel.purge(limit=amount)

    await send_modlog(
    interaction.guild,
    "🧹 Messages Cleared",
    [
    ("Moderator",interaction.user.mention),
    ("Channel",interaction.channel.mention),
    ("Amount",str(len(deleted)))
    ]
    )

    await interaction.response.send_message(
    f"Deleted {len(deleted)} messages",
    ephemeral=True
    )

# ---------------- DM COMMAND ----------------

@bot.tree.command(name="dm", description="Send a DM to a user")
@app_commands.checks.has_permissions(moderate_members=True)
async def dm(
    interaction: discord.Interaction,
    user: discord.Member,
    message: str
):

    try:

        embed = discord.Embed(
            title="📩 Message from the staff",
            description=message,
            color=discord.Color.blue()
        )

        embed.add_field(name="Server", value=interaction.guild.name)
        embed.set_footer(text=f"Sent by {interaction.user}")

        await user.send(embed=embed)

        await interaction.response.send_message(
            f"✅ DM sent to {user.mention}",
            ephemeral=True
        )

    except:

        await interaction.response.send_message(
            f"❌ Couldn't send DM to {user.mention} (DMs closed)",
            ephemeral=True
        )

# ---------------- START ----------------

bot.run(TOKEN)




