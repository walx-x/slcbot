# slcbot.py
import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from dotenv import load_dotenv
from datetime import timedelta

# Load variables from .env
load_dotenv()

# --- XP roles configuration ---
XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161,
}

# --- CONFIG ---
AUTO_BAN_WARNINGS = 3
LOG_CHANNEL_ID = 1479152748598399046  # --- NUOVO: canale modlogs

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

# ---------------- XP SYSTEM (INVARIATO) ----------------
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
            try: await member.add_roles(role, reason="XP threshold reached")
            except Exception: pass
    for role_id in to_remove:
        role = guild.get_role(role_id)
        if role:
            try: await member.remove_roles(role, reason="XP dropped below threshold")
            except Exception: pass

# ---------------- WARN SYSTEM ----------------
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

# ---------------- UTIL ----------------
async def send_log(guild, message: str):
    if LOG_CHANNEL_ID:
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(message)

# --- NUOVO: Invio DM alla warn ricevuta
async def send_warn_dm(user: discord.Member, reason: str, moderator: discord.Member):
    try:
        await user.send(f"⚠️ You received a warning from {moderator.mention} for: {reason}")
    except Exception:
        pass

# --- NUOVO: Invio DM di benvenuto
async def send_welcome_dm(member: discord.Member):
    try:
        await member.send(
            f"👋 Benvenuto {member.name}!\n"
            "Per verificarti usa ✅・verify\n"
            "Per diventare membro usa 👥・become-member\n"
            "Per aprire un ticket usa 🎫・create-ticket"
        )
    except Exception:
        pass

# ---------------- EVENTS ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online as {bot.user}")

# --- NUOVO: DM welcome on join
@bot.event
async def on_member_join(member: discord.Member):
    await send_welcome_dm(member)

# ---------------- XP COMMANDS (INVARIATI) ----------------
# ... (tutti i comandi xp_add, xp_remove, xp_set, xp_check rimangono invariati)

# ---------------- MODERATION ----------------
# ... (ban, kick, mute, unmute rimangono invariati)

# ---------------- WARN COMMANDS ----------------
@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn", description="Warn a user")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    add_warning(user.id, interaction.user.id, reason)
    warnings = get_warnings(user.id)
    await send_log(interaction.guild, f"⚠️ {user} warned | {reason}")
    await send_warn_dm(user, reason, interaction.user)  # --- NUOVO: DM warning
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

# ---------------- CLEAR MESSAGES COMMAND (NUOVO) ----------------
@app_commands.checks.has_permissions(manage_messages=True)
@bot.tree.command(name="clear", description="Delete messages in a channel")
async def clear(interaction: discord.Interaction, amount: str):
    channel = interaction.channel
    if amount.lower() == "all":
        deleted = await channel.purge()
        await interaction.response.send_message(f"🗑️ Deleted all messages ({len(deleted)} messages)", ephemeral=True)
    else:
        try:
            num = int(amount)
            deleted = await channel.purge(limit=num)
            await interaction.response.send_message(f"🗑️ Deleted {len(deleted)} messages", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Invalid number", ephemeral=True)

# ---------------- XP LEADERBOARD (NUOVO) ----------------
@bot.tree.command(name="xp_leaderboard", description="Show XP leaderboard")
async def xp_leaderboard(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, xp FROM xp ORDER BY xp DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        await interaction.response.send_message("No XP data found.")
        return
    embed = discord.Embed(title="🏆 XP Leaderboard", color=discord.Color.gold())
    for idx, (user_id, xp) in enumerate(rows, 1):
        member = interaction.guild.get_member(user_id)
        name = member.name if member else f"User ID {user_id}"
        embed.add_field(name=f"{idx}. {name}", value=f"{xp} XP", inline=False)
    await interaction.response.send_message(embed=embed)

# ---------------- WARNINGS COMMAND ----------------
# ... (già presente, mostra le warning)

# ---------------- CLEAR WARNINGS ----------------
# ... (già presente)

# ---------------- START ----------------
if __name__ == "__main__":
    bot.run(TOKEN)
