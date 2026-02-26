import discord
from discord.ext import commands
import json
import os

PREFIX = "!"
LEADERBOARD_FILE = "leaderboard.json"
PENDING_FILE = "pending.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ---------- Data Management ----------
def load_json(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

leaderboard = load_json(LEADERBOARD_FILE)
pending = load_json(PENDING_FILE)

def save_data():
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(leaderboard, f, indent=2)
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)

def record_match(winner_id, loser_id, result_type):
    """Calculates Elo and updates the leaderboard stats."""
    # Initialize players if new
    for p_id in [winner_id, loser_id]:
        if p_id not in leaderboard:
            leaderboard[p_id] = {"name": "Unknown", "wins": 0, "losses": 0, "draws": 0, "points": 1000}

    if result_type == "draw":
        leaderboard[winner_id]["draws"] += 1
        leaderboard[loser_id]["draws"] += 1
    else:
        # Elo Math: K-factor determines how much points swing per match
        K = 32
        w_points = leaderboard[winner_id]["points"]
        l_points = leaderboard[loser_id]["points"]
        
        expected_win = 1 / (1 + 10 ** ((l_points - w_points) / 400))
        gain = round(K * (1 - expected_win))

        leaderboard[winner_id]["points"] += gain
        leaderboard[loser_id]["points"] -= gain
        leaderboard[winner_id]["wins"] += 1
        leaderboard[loser_id]["losses"] += 1
    
    save_data()

# ---------- Player Report ----------
@bot.command(name="report")
async def report(ctx, opponent: discord.Member, result: str):
    reporter_id = str(ctx.author.id)
    opponent_id = str(opponent.id)
    result = result.lower()

    if result not in ["win", "loss", "draw"]:
        return await ctx.send("❌ Invalid result. Use `win`, `loss`, or `draw`.")

    # Sort IDs so match key is always the same regardless of who reports first
    match_key = f"{min(reporter_id, opponent_id)}-{max(reporter_id, opponent_id)}"
    
    pending.setdefault(match_key, {})
    pending[match_key][reporter_id] = result
    # Store the latest display name for the web/leaderboard
    leaderboard.setdefault(reporter_id, {"points": 1000, "wins":0, "losses":0, "draws":0})["name"] = ctx.author.display_name
    save_data()

    reports = pending[match_key]
    if len(reports) == 2:
        res1 = reports[reporter_id]
        res2 = reports[opponent_id]

        # Logic Fix: Checking for valid opposites
        if res1 == "draw" and res2 == "draw":
            await ctx.send("🤝 Draw confirmed and recorded!")
            record_match(reporter_id, opponent_id, "draw")
            
        elif res1 == "win" and res2 == "loss":
            await ctx.send(f"✅ Match confirmed! Winner: {ctx.author.display_name}")
            record_match(reporter_id, opponent_id, "win")
            
        elif res1 == "loss" and res2 == "win":
            await ctx.send(f"✅ Match confirmed! Winner: {opponent.display_name}")
            record_match(opponent_id, reporter_id, "win")
            
        else:
            await ctx.send(f"⚠️ **Conflict!** {ctx.author.display_name} reported '{res1}' and {opponent.display_name} reported '{res2}'. A judge is needed.")

        del pending[match_key]
        save_data()
    else:
        await ctx.send(f"📝 Report received! Waiting for **{opponent.display_name}** to confirm.")

# ---------- Judge & Leaderboard ----------
@bot.command(name="judge")
@commands.has_role("Judge")
async def judge(ctx, winner: discord.Member, loser: discord.Member):
    record_match(str(winner.id), str(loser.id), "win")
    await ctx.send(f"⚖️ Judge override: **{winner.display_name}** awarded win over **{loser.display_name}**.")

@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx):
    if not leaderboard:
        return await ctx.send("Leaderboard is empty.")
    
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1]["points"], reverse=True)
    msg = "**🏆 Grand Archive Arena Leaderboard**\n"
    for i, (uid, stats) in enumerate(sorted_board[:10], 1):
        msg += f"{i}. **{stats['name']}** — {stats['points']} pts (W:{stats['wins']} L:{stats['losses']})\n"
    await ctx.send(msg)

# ---------- Run ----------
TOKEN = os.environ["DISCORD_TOKEN"]
bot.run(TOKEN)
