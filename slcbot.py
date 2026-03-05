import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

MODLOG_CHANNEL = 1479152748598399046
AUTO_BAN_WARNINGS = 3

XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161
}

# ---------------- INTENTS ----------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------

conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS xp(
user_id INTEGER PRIMARY KEY,
xp INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
moderator_id INTEGER,
reason TEXT,
timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warned_users(
user_id INTEGER PRIMARY KEY,
first_warn DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ---------------- MODLOG ----------------

async def modlog(guild, embed):

    channel = guild.get_channel(MODLOG_CHANNEL)

    if channel:
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)

# ---------------- XP ----------------

def get_xp(user):

    cursor.execute("SELECT xp FROM xp WHERE user_id=?", (user,))
    row = cursor.fetchone()

    return row[0] if row else 0


def set_xp(user, xp):

    cursor.execute(
        "INSERT OR REPLACE INTO xp(user_id,xp) VALUES(?,?)",
        (user, xp)
    )

    conn.commit()


async def update_roles(member, xp):

    guild = member.guild

    should_have = {role for req, role in XP_ROLES.items() if xp >= req}
    current = {r.id for r in member.roles}

    for role_id in should_have - current:

        role = guild.get_role(role_id)

        if role:
            await member.add_roles(role)

# ---------------- WARN ----------------

def add_warning(user, mod, reason):

    cursor.execute(
        "INSERT INTO warnings(user_id, moderator_id, reason) VALUES(?,?,?)",
        (user, mod, reason)
    )

    cursor.execute(
        "INSERT OR IGNORE INTO warned_users(user_id) VALUES(?)",
        (user,)
    )

    conn.commit()


def get_warnings(user):

    cursor.execute(
        "SELECT id, moderator_id, reason, timestamp FROM warnings WHERE user_id=?",
        (user,)
    )

    return cursor.fetchall()


def clear_warnings_db(user):

    cursor.execute(
        "DELETE FROM warnings WHERE user_id=?",
        (user,)
    )

    conn.commit()

# ---------------- READY ----------------

@bot.event
async def on_ready():

    await bot.tree.sync()

    print(f"Bot online: {bot.user}")

# ---------------- MEMBER JOIN DM ----------------

@bot.event
async def on_member_join(member):

    embed = discord.Embed(
        title="Welcome!",
        description=(
            "Welcome to the server!\n\n"
            "Please verify yourself in the **Verify** channel.\n\n"
            "When you're ready go to **Become A Member** "
            "and open a ticket."
        ),
        color=discord.Color.green()
    )

    try:
        await member.send(embed=embed)
    except:
        pass

# ---------------- LEADERBOARD ----------------

@bot.tree.command(name="leaderboard")
async def leaderboard(interaction: discord.Interaction):

    cursor.execute(
        "SELECT user_id,xp FROM xp ORDER BY xp DESC LIMIT 10"
    )

    data = cursor.fetchall()

    embed = discord.Embed(
        title="XP Leaderboard",
        color=discord.Color.gold()
    )

    text = ""

    for i, (user_id, xp) in enumerate(data, start=1):

        member = interaction.guild.get_member(user_id)

        name = member.display_name if member else user_id

        text += f"{i}. {name} — {xp} XP\n"

    embed.description = text

    await interaction.response.send_message(embed=embed)

# ---------------- XP CHECK ----------------

@bot.tree.command(name="xp_check")
async def xp_check(interaction: discord.Interaction, user: discord.Member=None):

    user = user or interaction.user

    xp = get_xp(user.id)

    embed = discord.Embed(
        title=f"{user.display_name} XP",
        color=discord.Color.blue()
    )

    embed.add_field(name="XP", value=xp)

    await interaction.response.send_message(embed=embed)

# ---------------- CLEAR CHAT ----------------

@app_commands.checks.has_permissions(manage_messages=True)
@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):

    await interaction.response.defer(ephemeral=True)

    deleted = await interaction.channel.purge(limit=amount)

    embed = discord.Embed(
        title="Chat Cleared",
        color=discord.Color.orange()
    )

    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Messages", value=len(deleted))

    await modlog(interaction.guild, embed)

    await interaction.followup.send(
        f"Deleted {len(deleted)} messages",
        ephemeral=True
    )

# ---------------- BAN ----------------

@app_commands.checks.has_permissions(ban_members=True)
@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str="No reason"):

    await user.ban(reason=reason)

    embed = discord.Embed(title="Ban", color=discord.Color.red())

    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)

    await modlog(interaction.guild, embed)

    await interaction.response.send_message("User banned")

# ---------------- KICK ----------------

@app_commands.checks.has_permissions(kick_members=True)
@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str="No reason"):

    await user.kick(reason=reason)

    embed = discord.Embed(title="Kick", color=discord.Color.orange())

    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)

    await modlog(interaction.guild, embed)

    await interaction.response.send_message("User kicked")

# ---------------- MUTE ----------------

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="mute")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str="No reason"):

    await user.timeout(timedelta(minutes=minutes))

    embed = discord.Embed(title="Mute", color=discord.Color.yellow())

    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Duration", value=f"{minutes} minutes")

    await modlog(interaction.guild, embed)

    await interaction.response.send_message("User muted")

# ---------------- UNMUTE ----------------

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="unmute")
async def unmute(interaction: discord.Interaction, user: discord.Member):

    await user.timeout(None)

    embed = discord.Embed(title="Unmute", color=discord.Color.green())

    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)

    await modlog(interaction.guild, embed)

    await interaction.response.send_message("User unmuted")

# ---------------- WARN ----------------

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):

    add_warning(user.id, interaction.user.id, reason)

    warns = get_warnings(user.id)

    embed = discord.Embed(
        title="Warning",
        color=discord.Color.orange()
    )

    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)
    embed.add_field(name="Total Warnings", value=len(warns))

    await modlog(interaction.guild, embed)

    if len(warns) >= AUTO_BAN_WARNINGS:

        await user.ban(reason="Too many warnings")

        await interaction.response.send_message(
            f"{user.mention} auto banned (too many warnings)"
        )

        return

    await interaction.response.send_message(
        f"{user.mention} warned ({len(warns)})"
    )

# ---------------- WARNINGS ----------------

@bot.tree.command(name="warnings")
async def warnings(interaction: discord.Interaction, user: discord.Member):

    data = get_warnings(user.id)

    if not data:

        await interaction.response.send_message("No warnings")

        return

    text = ""

    for warn_id, mod, reason, time in data:

        text += f"ID {warn_id} | {reason} | {time}\n"

    await interaction.response.send_message(text[:1900])

# ---------------- WARNINGS ALL ----------------

@bot.tree.command(name="warnings_all")
async def warnings_all(interaction: discord.Interaction):

    cursor.execute("SELECT user_id, reason FROM warnings")

    data = cursor.fetchall()

    text = ""

    for user, reason in data:

        member = interaction.guild.get_member(user)

        name = member.mention if member else user

        text += f"{name} | {reason}\n"

    await interaction.response.send_message(text[:1900])

# ---------------- WARNED USERS ----------------

@bot.tree.command(name="warned_users")
async def warned_users(interaction: discord.Interaction):

    cursor.execute("SELECT user_id FROM warned_users")

    data = cursor.fetchall()

    text = ""

    for user_id, in data:

        member = interaction.guild.get_member(user_id)

        if member:
            text += f"{member.mention}\n"
        else:
            text += f"{user_id}\n"

    await interaction.response.send_message(text[:1900])

# ---------------- CLEAR WARNINGS ----------------

@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="clear_warnings")
async def clear_warnings(interaction: discord.Interaction, user: discord.Member):

    clear_warnings_db(user.id)

    await interaction.response.send_message(
        f"Warnings cleared for {user.mention}"
    )

# ---------------- START ----------------

bot.run(TOKEN)
