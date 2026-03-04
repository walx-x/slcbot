# slcbot.py
import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from dotenv import load_dotenv
from datetime import timedelta

# Load variables from .env (if present)
load_dotenv()

# --- XP roles configuration ---
XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161,
}

# --- CONFIG ---
AUTO_BAN_WARNINGS = 3  # Auto-ban after X warnings
LOG_CHANNEL_ID = None  # Metti ID canale log oppure lascia None

# --- Intents ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Token ---
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Token not found: set DISCORD_BOT_TOKEN")

# --- Database ---
DB_PATH = "xp.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS xp (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ---------------- XP SYSTEM (INVARIATO) ---------------- #

def get_xp(user_id: int) -> int:
    cursor.execute("SELECT xp FROM xp WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def set_xp(user_id: int, amount: int) -> None:
    cursor.execute("INSERT OR REPLACE INTO xp (user_id, xp) VALUES (?, ?)", (user_id, amount))
    conn.commit()

async def update_roles(member: discord.Member, xp: int) -> None:
    guild = member.guild
    should_have = {role_id for req, role_id in XP_ROLES.items() if xp >= req}
    current_role_ids = {r.id for r in member.roles}

    to_add = should_have - current_role_ids
    to_remove = {role_id for req, role_id in XP_ROLES.items() if xp < req and role_id in current_role_ids}

    for role_id in to_add:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role, reason="XP threshold reached")
            except Exception:
                pass

    for role_id in to_remove:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.remove_roles(role, reason="XP dropped below threshold")
            except Exception:
                pass

# ---------------- WARN SYSTEM ---------------- #

def add_warning(user_id: int, moderator_id: int, reason: str):
    cursor.execute(
        "INSERT INTO warnings (user_id, moderator_id, reason) VALUES (?, ?, ?)",
        (user_id, moderator_id, reason)
    )
    conn.commit()

def get_warnings(user_id: int):
    cursor.execute(
        "SELECT id, moderator_id, reason, timestamp FROM warnings WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchall()

def clear_warnings(user_id: int):
    cursor.execute("DELETE FROM warnings WHERE user_id = ?", (user_id,))
    conn.commit()

# ---------------- UTIL ---------------- #

async def send_log(guild, message: str):
    if LOG_CHANNEL_ID:
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(message)

# ---------------- EVENTS ---------------- #

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online as {bot.user}")

# ---------------- XP COMMANDS (INVARIATI) ---------------- #

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_add", description="Add XP to a user")
async def xp_add(interaction: discord.Interaction, user: discord.Member, amount: int):
    xp = get_xp(user.id) + amount
    set_xp(user.id, xp)
    await update_roles(user, xp)
    await interaction.response.send_message(
        f"✅ {amount} XP added to {user.mention} (Total: {xp})"
    )

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_remove", description="Remove XP from a user")
async def xp_remove(interaction: discord.Interaction, user: discord.Member, amount: int):
    xp = max(0, get_xp(user.id) - amount)
    set_xp(user.id, xp)
    await update_roles(user, xp)
    await interaction.response.send_message(
        f"❌ {amount} XP removed from {user.mention} (Total: {xp})"
    )

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_set", description="Set XP")
async def xp_set(interaction: discord.Interaction, user: discord.Member, amount: int):
    set_xp(user.id, amount)
    await update_roles(user, amount)
    await interaction.response.send_message(
        f"🎯 XP for {user.mention} set to {amount}"
    )

@bot.tree.command(name="xp_check", description="Check a user's XP")
async def xp_check(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    xp = get_xp(user.id)

    # Determine current and next rank
    sorted_roles = sorted(XP_ROLES.items())
    current_rank = "Unranked"
    next_rank = None
    next_xp = None

    for req, role_id in sorted_roles:
        if xp >= req:
            current_rank = interaction.guild.get_role(role_id).name
        else:
            next_rank = interaction.guild.get_role(role_id).name
            next_xp = req
            break

    # Progress bar
    if next_xp:
        progress = xp / next_xp
        filled = int(progress * 20)
        bar = "█" * filled + "░" * (20 - filled)
        remaining = next_xp - xp
        progress_percent = round(progress * 100, 1)
    else:
        bar = "████████████████████"
        remaining = 0
        progress_percent = 100.0

    # Embed
    embed = discord.Embed(
        title=f"{user.display_name}'s XP Profile",
        color=discord.Color.blue()
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(
        name="Rank",
        value=f"**{current_rank}**",
        inline=True
    )

    embed.add_field(
        name="XP",
        value=f"**{xp} XP**",
        inline=True
    )

    if next_rank:
        embed.add_field(
            name="Next Rank",
            value=f"**{next_rank}** ({remaining} XP remaining)",
            inline=False
        )
    else:
        embed.add_field(
            name="Next Rank",
            value="Max rank reached",
            inline=False
        )

    embed.add_field(
        name="Progress",
        value=f"`{bar}`\n**{progress_percent}%**",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

# ---------------- MODERATION ---------------- #

@app_commands.checks.has_permissions(ban_members=True)
@bot.tree.command(name="ban", description="Ban a user")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await user.ban(reason=reason)
    await send_log(interaction.guild, f"🔨 {user} banned | {reason}")
    await interaction.response.send_message(f"🔨 {user.mention} banned.")

@app_commands.checks.has_permissions(kick_members=True)
@bot.tree.command(name="kick", description="Kick a user")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await user.kick(reason=reason)
    await send_log(interaction.guild, f"👢 {user} kicked | {reason}")
    await interaction.response.send_message(f"👢 {user.mention} kicked.")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="mute", description="Timeout a user")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str = "No reason provided"):
    await user.timeout(timedelta(minutes=minutes), reason=reason)
    await send_log(interaction.guild, f"🔇 {user} muted {minutes}m | {reason}")
    await interaction.response.send_message(f"🔇 {user.mention} muted for {minutes} minutes.")

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="unmute", description="Remove timeout")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    await user.timeout(None)
    await send_log(interaction.guild, f"🔊 {user} unmuted")
    await interaction.response.send_message(f"🔊 {user.mention} unmuted.")

# ---------------- WARN COMMANDS ---------------- #

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn", description="Warn a user")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    add_warning(user.id, interaction.user.id, reason)
    warnings = get_warnings(user.id)

    await send_log(interaction.guild, f"⚠️ {user} warned | {reason}")

    if len(warnings) >= AUTO_BAN_WARNINGS:
        await user.ban(reason="Too many warnings")
        await send_log(interaction.guild, f"🔨 {user} auto-banned (warnings limit reached)")
        await interaction.response.send_message(
            f"⚠️ {user.mention} warned and auto-banned (limit reached)."
        )
        return

    await interaction.response.send_message(
        f"⚠️ {user.mention} warned.\nTotal warnings: {len(warnings)}"
    )

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings", description="Check warnings")
async def warnings(interaction: discord.Interaction, user: discord.Member):
    data = get_warnings(user.id)

    if not data:
        await interaction.response.send_message("✅ No warnings.")
        return

    text = ""
    for warn_id, mod_id, reason, timestamp in data:
        text += f"ID {warn_id} | {reason} | {timestamp}\n"

    await interaction.response.send_message(text)

@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="clear_warnings", description="Clear warnings")
async def clear_user_warnings(interaction: discord.Interaction, user: discord.Member):
    clear_warnings(user.id)
    await interaction.response.send_message(f"🗑️ Warnings cleared for {user.mention}")

# ---------------- START ---------------- #

if __name__ == "__main__":
    bot.run(TOKEN)