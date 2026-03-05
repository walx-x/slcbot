# slcbot.py

import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# -------- CONFIG -------- #

AUTO_BAN_WARNINGS = 3
LOG_CHANNEL_ID = 1479141762554527845

XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161,
}

# -------- BOT -------- #

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------- DATABASE -------- #

conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS xp (
user_id INTEGER PRIMARY KEY,
xp INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
moderator_id INTEGER,
reason TEXT,
timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# -------- XP FUNCTIONS -------- #

def get_xp(user_id):
    cursor.execute("SELECT xp FROM xp WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def set_xp(user_id, xp):
    cursor.execute("INSERT OR REPLACE INTO xp (user_id,xp) VALUES (?,?)",(user_id,xp))
    conn.commit()

async def update_roles(member, xp):

    should_have = {role for req,role in XP_ROLES.items() if xp >= req}
    current = {r.id for r in member.roles}

    for role_id in should_have - current:
        role = member.guild.get_role(role_id)
        if role:
            await member.add_roles(role)

    for req,role_id in XP_ROLES.items():
        if xp < req and role_id in current:
            role = member.guild.get_role(role_id)
            if role:
                await member.remove_roles(role)

# -------- WARN FUNCTIONS -------- #

def add_warning(user_id, mod_id, reason):
    cursor.execute(
        "INSERT INTO warnings (user_id, moderator_id, reason) VALUES (?,?,?)",
        (user_id, mod_id, reason)
    )
    conn.commit()

def get_warnings(user_id):
    cursor.execute("SELECT * FROM warnings WHERE user_id=?", (user_id,))
    return cursor.fetchall()

def clear_warnings(user_id):
    cursor.execute("DELETE FROM warnings WHERE user_id=?", (user_id,))
    conn.commit()

# -------- LOG -------- #

async def log(guild, embed):

    channel = guild.get_channel(LOG_CHANNEL_ID)

    if channel:
        await channel.send(embed=embed)

# -------- READY -------- #

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online: {bot.user}")

# -------- XP COMMANDS -------- #

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_add")
async def xp_add(interaction: discord.Interaction, user: discord.Member, amount:int):

    xp = get_xp(user.id) + amount
    set_xp(user.id, xp)

    await update_roles(user, xp)

    await interaction.response.send_message(
        f"✅ Added {amount} XP to {user.mention} (Total: {xp})"
    )

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_remove")
async def xp_remove(interaction: discord.Interaction, user: discord.Member, amount:int):

    xp = max(0, get_xp(user.id) - amount)
    set_xp(user.id, xp)

    await update_roles(user, xp)

    await interaction.response.send_message(
        f"❌ Removed {amount} XP from {user.mention} (Total: {xp})"
    )

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_set")
async def xp_set(interaction: discord.Interaction, user: discord.Member, amount:int):

    set_xp(user.id, amount)

    await update_roles(user, amount)

    await interaction.response.send_message(
        f"🎯 XP set to {amount} for {user.mention}"
    )

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

# -------- MODERATION -------- #

@app_commands.checks.has_permissions(ban_members=True)
@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, user:discord.Member, reason:str="No reason"):

    await user.ban(reason=reason)

    embed = discord.Embed(
        title="🔨 Ban",
        description=f"{user.mention} banned",
        color=discord.Color.red()
    )

    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)

    await log(interaction.guild, embed)

    await interaction.response.send_message("User banned")

@app_commands.checks.has_permissions(kick_members=True)
@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, user:discord.Member, reason:str="No reason"):

    await user.kick(reason=reason)

    await interaction.response.send_message("User kicked")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="mute")
async def mute(interaction:discord.Interaction, user:discord.Member, minutes:int):

    await user.timeout(timedelta(minutes=minutes))

    await interaction.response.send_message(f"Muted {user.mention}")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="unmute")
async def unmute(interaction:discord.Interaction, user:discord.Member):

    await user.timeout(None)

    await interaction.response.send_message("Unmuted")

# -------- WARN COMMANDS -------- #

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn")
async def warn(interaction:discord.Interaction, user:discord.Member, reason:str):

    add_warning(user.id, interaction.user.id, reason)

    warnings = get_warnings(user.id)

    embed = discord.Embed(
        title="⚠️ Warning",
        color=discord.Color.orange()
    )

    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Moderator", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)
    embed.add_field(name="Total warnings", value=len(warnings))

    await log(interaction.guild, embed)

    if len(warnings) >= AUTO_BAN_WARNINGS:

        await user.ban(reason="Too many warnings")

        await interaction.response.send_message(
            f"{user.mention} auto banned (too many warnings)"
        )

        return

    await interaction.response.send_message(
        f"{user.mention} warned ({len(warnings)})"
    )

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings")
async def warnings(interaction:discord.Interaction, user:discord.Member):

    data = get_warnings(user.id)

    if not data:
        await interaction.response.send_message("No warnings")
        return

    text = ""

    for warn in data:

        text += f"ID {warn[0]} | {warn[3]}\n"

    await interaction.response.send_message(text)

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings_all")
async def warnings_all(interaction:discord.Interaction):

    cursor.execute("SELECT * FROM warnings")

    data = cursor.fetchall()

    if not data:
        await interaction.response.send_message("No warnings")
        return

    text=""

    for warn in data:

        text += f"UserID {warn[1]} | Reason: {warn[3]}\n"

    await interaction.response.send_message(text[:1900])

@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="clear_warnings")
async def clear_warnings_cmd(interaction:discord.Interaction, user:discord.Member):

    clear_warnings(user.id)

    await interaction.response.send_message("Warnings cleared")

# -------- START -------- #

bot.run(TOKEN)
