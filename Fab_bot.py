import discord
from discord.ext import commands
import json

PREFIX = "!"
LEADERBOARD_FILE = "leaderboard.json"
PENDING_FILE = "pending.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Load or initialize data
try:
    with open(LEADERBOARD_FILE, "r") as f:
        leaderboard = json.load(f)
except FileNotFoundError:
    leaderboard = {}

try:
    with open(PENDING_FILE, "r") as f:
        pending = json.load(f)
except FileNotFoundError:
    pending = {}

def save_data():
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(leaderboard, f, indent=2)
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)

# ---------- Player Report ----------
@bot.command(name="report")
async def report(ctx, opponent: discord.Member, result: str):
    reporter = str(ctx.author.id)
    opponent_id = str(opponent.id)
    result = result.lower()

    if result not in ["win", "loss", "draw"]:
        return await ctx.send("Invalid result. Use `win`, `loss`, or `draw`.")

    # Store report in pending
    match_key = f"{min(reporter, opponent_id)}-{max(reporter, opponent_id)}"
    pending.setdefault(match_key, {})
    pending[match_key][reporter] = result
    save_data()

    # Check if both players reported
    reports = pending[match_key]
    if len(reports) == 2:
        reporter_result = reports[reporter]
        opponent_result = reports[opponent_id]

        # Impossible scenario: both claim win
        if reporter_result == "win" and opponent_result == "win":
            await ctx.send(f"Invalid reports: both players reported 'win'. Judge needed: {ctx.author.display_name} vs {opponent.display_name}")
        # Impossible scenario: both claim loss
        elif reporter_result == "loss" and opponent_result == "loss":
            await ctx.send(f"Invalid reports: both players reported 'loss'. Judge needed: {ctx.author.display_name} vs {opponent.display_name}")
        # Both agree on draw
        elif reporter_result == "draw" and opponent_result == "draw":
            await ctx.send(f"Both players agree on a draw! Recording match: {ctx.author.display_name} vs {opponent.display_name}")
            record_match(reporter, opponent_id, "draw")
        # Standard case: one win, one loss
        elif (reporter_result == "win" and opponent_result == "loss") or (reporter_result == "loss" and opponent_result == "win"):
            winner_id = reporter if reporter_result == "win" else opponent_id
            loser_id = opponent_id if winner_id == reporter else reporter
            await ctx.send(f"Match recorded: {ctx.author.display_name} vs {opponent.display_name} — Winner: {bot.get_user(int(winner_id)).name}")
            record_match(winner_id, loser_id, "win")
        # Any other unexpected combination
        else:
            await ctx.send(f"Conflict detected! Staff please review match: {ctx.author.display_name} vs {opponent.display_name}")

        # Clear pending after processing
        del pending[match_key]
        save_data()
    else:
        await ctx.send(f"Report received! Waiting for opponent to submit result.")

# ---------- Judge Override ----------
@bot.command(name="judge")
@commands.has_role("Judge")  # Only staff with "Judge" role can use
async def judge(ctx, player1: discord.Member, player2: discord.Member, result: str):
    result = result.lower()
    if result not in ["win", "loss", "draw"]:
        return await ctx.send("Invalid result. Use `win`, `loss`, or `draw`.")
    p1_id, p2_id = str(player1.id), str(player2.id)
    match_key = f"{min(p1_id, p2_id)}-{max(p1_id, p2_id)}"
    record_match(p1_id, p2_id, result)
    if match_key in pending:
        del pending[match_key]
    save_data()
    await ctx.send(f"Judge override applied: {player1.display_name} vs {player2.display_name} — {result}")

# ---------- Solo Test Command ----------
@bot.command(name="testmatch")
async def testmatch(ctx, player: str, points: int):
    """
    Adds points to any player for solo testing purposes.
    """
    # Make sure the player exists in leaderboard
    leaderboard.setdefault(player, {"wins":0, "losses":0, "draws":0, "points":0})
    leaderboard[player]["points"] += points
    await ctx.send(f"✅ {player} now has {leaderboard[player]['points']} points!")
    save_data()

# ---------- Leaderboard ----------
@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx):
    if not leaderboard:
        return await ctx.send("Leaderboard is empty.")
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1]["points"], reverse=True)
    message = "**FaB Arena – Leaderboard**\n"
    for user_id, stats in sorted_board:
        user = await bot.fetch_user(int(user_id))
        message += f"{user.name} — {stats['points']} pts (W:{stats['wins']} D:{stats['draws']} L:{stats['losses']})\n"
    await ctx.send(message)

import os

TOKEN = os.environ["DISCORD_TOKEN"]

bot.run(TOKEN)
