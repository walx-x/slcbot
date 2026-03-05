# slcbot.py
import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from dotenv import load_dotenv
from datetime import timedelta

# --- Load environment variables ---
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Token not found: set DISCORD_BOT_TOKEN")

# --- XP roles configuration ---
XP_ROLES = {
    100: 1478412603557544128,
    300: 1478412692082659529,
    600: 1475526619132203161,
}

# --- CONFIG ---
AUTO_BAN_WARNINGS = 3
LOG_CHANNEL_ID = 1479152748598399046  # Modlogs channel

# --- Intents ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Database setup ---
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

# ---------------- XP SYSTEM ----------------
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

async def send_warn_dm(user: discord.Member, reason: str, moderator: discord.Member):
    try:
        await user.send(f"⚠️ You received a warning from {moderator.mention} for: {reason}")
    except Exception:
        pass

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

@bot.event
async def on_member_join(member: discord.Member):
    await send_welcome_dm(member)

# ---------------- XP COMMANDS ----------------
@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_add", description="Add XP to a user")
async def xp_add(interaction: discord.Interaction, user: discord.Member, amount: int):
    xp = get_xp(user.id) + amount
    set_xp(user.id, xp)
    await update_roles(user, xp)
    await interaction.response.send_message(f"✅ {amount} XP added to {user.mention} (Total: {xp})")

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_remove", description="Remove XP from a user")
async def xp_remove(interaction: discord.Interaction, user: discord.Member, amount: int):
    xp = max(0, get_xp(user.id) - amount)
    set_xp(user.id, xp)
    await update_roles(user, xp)
    await interaction.response.send_message(f"❌ {amount} XP removed from {user.mention} (Total: {xp})")

@app_commands.checks.has_permissions(manage_roles=True)
@bot.tree.command(name="xp_set", description="Set XP")
async def xp_set(interaction: discord.Interaction, user: discord.Member, amount: int):
    set_xp(user.id, amount)
    await update_roles(user, amount)
    await interaction.response.send_message(f"🎯 XP for {user.mention} set to {amount}")

@bot.tree.command(name="xp_check", description="Check a user's XP")
async def xp_check(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    xp = get_xp(user.id)
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
    embed = discord.Embed(title=f"{user.display_name}'s XP Profile", color=discord.Color.blue())
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Rank", value=f"**{current_rank}**", inline=True)
    embed.add_field(name="XP", value=f"**{xp} XP**", inline=True)
    if next_rank:
        embed.add_field(name="Next Rank", value=f"**{next_rank}** ({remaining} XP remaining)", inline=False)
    else:
        embed.add_field(name="Next Rank", value="Max rank reached", inline=False)
    embed.add_field(name="Progress", value=f"{bar}\n**{progress_percent}%**", inline=False)
    await interaction.response.send_message(embed=embed)

# ---------------- MODERATION ----------------
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

# ---------------- WARN COMMANDS ----------------
@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warn", description="Warn a user")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    add_warning(user.id, interaction.user.id, reason)
    warnings = get_warnings(user.id)

    # --- Modlog embed ---
    embed = discord.Embed(title="⚠️ Warning", color=discord.Color.orange())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=str(len(warnings)), inline=False)
    embed.set_footer(text=f"Oggi alle {interaction.created_at.strftime('%H:%M')}")

    # Send to modlog channel
    if LOG_CHANNEL_ID:
        channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

    # DM the warned user
    await send_warn_dm(user, reason, interaction.user)

    # Auto-ban check
    if len(warnings) >= AUTO_BAN_WARNINGS:
        await user.ban(reason="Too many warnings")
        await send_log(interaction.guild, f"🔨 {user} auto-banned (warnings limit reached)")
        await interaction.response.send_message(
            f"⚠️ {user.mention} warned and auto-banned (limit reached)."
        )
    else:
        # Solo un messaggio, sempre
        await interaction.response.send_message(
            f"⚠️ {user.mention} warned.\nTotal warnings: {len(warnings)}"
        )

@app_commands.checks.has_permissions(moderate_members=True)
@bot.tree.command(name="warnings", description="Check warnings")
async def warnings_cmd(interaction: discord.Interaction, user: discord.Member):
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

@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="warnings_all", description="Show all warnings given to all users")
async def warnings_all(interaction: discord.Interaction):
    cursor.execute("SELECT id, user_id, moderator_id, reason, timestamp FROM warnings ORDER BY timestamp DESC")
    data = cursor.fetchall()

    if not data:
        await interaction.response.send_message("✅ No warnings recorded.")
        return

    text = ""
    for warn_id, user_id, mod_id, reason, timestamp in data:
        member = interaction.guild.get_member(user_id)
        moderator = interaction.guild.get_member(mod_id)
        user_name = member.name if member else f"User ID {user_id}"
        mod_name = moderator.name if moderator else f"User ID {mod_id}"
        text += f"ID {warn_id} | User: {user_name} | Moderator: {mod_name} | Reason: {reason} | {timestamp}\n"

    # Discord non permette messaggi troppo lunghi, quindi si può mandare in chunk da 2000 caratteri
    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
    await interaction.response.send_message(f"📜 All Warnings (total {len(data)}):")
    for chunk in chunks:
        await interaction.followup.send(chunk)

# ---------------- CLEAR MESSAGES COMMAND ----------------
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

# ---------------- XP LEADERBOARD ----------------
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

# ---------------- START ----------------
if __name__ == "__main__":
    bot.run(TOKEN)



