import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
AUTO_BAN_WARNINGS = 3
MODLOG_CHANNEL = 1479152748598399046

XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161
}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS xp(
    user_id INTEGER PRIMARY KEY,
    xp INTEGER
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
    first_warn TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages(
    user_id INTEGER PRIMARY KEY,
    count INTEGER
)
""")

conn.commit()

# ---------------- MODLOG ----------------
async def modlog(guild, embed):
    channel = guild.get_channel(MODLOG_CHANNEL)
    if channel:
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)

# ---------------- XP SYSTEM ----------------
def get_xp(user_id):
    cursor.execute("SELECT xp FROM xp WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def set_xp(user_id, xp):
    cursor.execute(
        "INSERT OR REPLACE INTO xp(user_id,xp) VALUES(?,?)",
        (user_id, xp)
    )
    conn.commit()

async def update_roles(member, xp):
    guild = member.guild
    should_have = {role_id for req, role_id in XP_ROLES.items() if xp >= req}
    current = {r.id for r in member.roles}

    for role_id in should_have - current:
        role = guild.get_role(role_id)
        if role:
            await member.add_roles(role)

    for req, role_id in XP_ROLES.items():
        if xp < req and role_id in current:
            role = guild.get_role(role_id)
            if role:
                await member.remove_roles(role)

# ---------------- WARN SYSTEM ----------------
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
    cursor.execute("SELECT * FROM warnings WHERE user_id=?", (user,))
    return cursor.fetchall()

def clear_warnings_db(user):
    cursor.execute("DELETE FROM warnings WHERE user_id=?", (user,))
    conn.commit()

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online: {bot.user}")

@bot.event
async def on_member_join(member):
    try:
        await member.send(
            f"Welcome to **{member.guild.name}**!\n\n"
            "Please verify yourself in the **Verify** channel.\n"
            "When you are ready go to **Become A Member** and open a ticket."
        )
    except:
        pass

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    cursor.execute("SELECT count FROM messages WHERE user_id=?", (message.author.id,))
    data = cursor.fetchone()
    if data:
        cursor.execute("UPDATE messages SET count=count+1 WHERE user_id=?", (message.author.id,))
    else:
        cursor.execute("INSERT INTO messages(user_id,count) VALUES(?,1)", (message.author.id,))
    conn.commit()

    await bot.process_commands(message)

# ---------------- XP COMMANDS ----------------
@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_add")
async def xp_add(interaction: discord.Interaction, user: discord.Member, amount: int):
    xp = get_xp(user.id) + amount
    set_xp(user.id, xp)
    await update_roles(user, xp)
    await interaction.response.send_message(f"Added {amount} XP to {user.mention} (Total {xp})")

@app_commands.command(name="xp_check")
async def xp_check(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    xp = get_xp(user.id)
    embed = discord.Embed(title=f"{user.display_name} XP", color=discord.Color.blue())
    embed.add_field(name="XP", value=xp)
    await interaction.response.send_message(embed=embed)

@app_commands.command(name="leaderboard")
async def leaderboard(interaction: discord.Interaction):
    cursor.execute("SELECT user_id,count FROM messages ORDER BY count DESC LIMIT 10")
    data = cursor.fetchall()
    embed = discord.Embed(title="🏆 Message Leaderboard", color=discord.Color.gold())
    text = ""
    for i, (user_id, count) in enumerate(data, start=1):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member else str(user_id)
        text += f"{i}. {name} — {count} messages\n"
    embed.description = text
    await interaction.response.send_message(embed=embed)

# ---------------- CLEAR CHAT ----------------
@app_commands.checks.has_permissions(manage_messages=True)
@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    embed = discord.Embed(title="🧹 Chat Cleared", color=discord.Color.orange())
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Messages", value=len(deleted))
    embed.add_field(name="Channel", value=interaction.channel.mention)
    await modlog(interaction.guild, embed)
    await interaction.followup.send(f"Deleted {len(deleted)} messages", ephemeral=True)

# ---------------- MODERATION ----------------
@app_commands.checks.has_permissions(ban_members=True)
@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    await user.ban(reason=reason)
    embed = discord.Embed(title="🔨 Ban", color=discord.Color.red())
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)
    await modlog(interaction.guild, embed)
    await interaction.response.send_message("User banned")

@app_commands.checks.has_permissions(kick_members=True)
@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    await user.kick(reason=reason)
    embed = discord.Embed(title="👢 Kick", color=discord.Color.orange())
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)
    await modlog(interaction.guild, embed)
    await interaction.response.send_message("User kicked")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="mute")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str = "No reason"):
    await user.timeout(timedelta(minutes=minutes))
    embed = discord.Embed(title="🔇 Mute", color=discord.Color.yellow())
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Duration", value=f"{minutes} minutes")
    embed.add_field(name="Reason", value=reason)
    await modlog(interaction.guild, embed)
    await interaction.response.send_message("User muted")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="unmute")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    await user.timeout(None)
    embed = discord.Embed(title="🔊 Unmute", color=discord.Color.green())
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    await modlog(interaction.guild, embed)
    await interaction.response.send_message("User unmuted")

# ---------------- WARNINGS ----------------
@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    add_warning(user.id, interaction.user.id, reason)
    warns = get_warnings(user.id)
    embed = discord.Embed(title="⚠️ Warning", color=discord.Color.orange())
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)
    embed.add_field(name="Total Warnings", value=len(warns))
    await modlog(interaction.guild, embed)
    if len(warns) >= AUTO_BAN_WARNINGS:
        await user.ban(reason="Too many warnings")
        await interaction.response.send_message(f"{user.mention} auto banned (too many warnings)")
        return
    await interaction.response.send_message(f"{user.mention} warned ({len(warns)})")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings")
async def warnings(interaction: discord.Interaction, user: discord.Member):
    data = get_warnings(user.id)
    if not data:
        await interaction.response.send_message("No warnings")
        return
    text = ""
    for w in data:
        text += f"ID {w[0]} | {w[3]}\n"
    await interaction.response.send_message(text[:1900])

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings_all")
async def warnings_all(interaction: discord.Interaction):
    cursor.execute("SELECT * FROM warnings")
    data = cursor.fetchall()
    if not data:
        await interaction.response.send_message("No warnings")
        return
    text = ""
    for w in data:
        text += f"User {w[1]} | {w[3]}\n"
    await interaction.response.send_message(text[:1900])

@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="clear_warnings")
async def clear_warnings(interaction: discord.Interaction, user: discord.Member):
    clear_warnings_db(user.id)
    await interaction.response.send_message("Warnings cleared")

@app_commands.checks.has_permissions(moderate_members=True)
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
    if not text:
        text = "No warned users"
    await interaction.response.send_message(text)

# ---------------- RUN ----------------
bot.run(TOKEN)
