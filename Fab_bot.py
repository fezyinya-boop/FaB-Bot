import discord
from discord.ext import commands
import json
import os

from flask import Flask, render_template_string
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    # Sort players by points (Elo) for the web view
    sorted_players = sorted(leaderboard.items(), key=lambda x: x[1]['points'], reverse=True)
    
    table_rows = ""
    for i, (uid, stats) in enumerate(sorted_players, 1):
        # Determine a "Tier" color for the web row
        color = "#ffd700" if i == 1 else "#c0c0c0" if i == 2 else "#cd7f32" if i == 3 else "#ffffff"
        table_rows += f"""
        <tr style="color: {color}">
            <td>{i}</td>
            <td>{stats.get('name', 'Unknown')}</td>
            <td>{stats['points']}</td>
            <td>{stats['wins']}W - {stats['losses']}L</td>
        </tr>
        """

    return render_template_string(f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>GA Leaderboard</title>
        <style>
            body {{ background-color: #121212; color: white; font-family: sans-serif; text-align: center; }}
            table {{ margin: 50px auto; border-collapse: collapse; width: 80%; background: #1e1e1e; border-radius: 10px; overflow: hidden; }}
            th, td {{ padding: 15px; border-bottom: 1px solid #333; }}
            th {{ background-color: #333; text-transform: uppercase; letter-spacing: 1px; }}
            h1 {{ color: #00d4ff; margin-top: 30px; }}
        </style>
    </head>
    <body>
        <h1>🏆 Archive Arena Leaderboard 🏆 </h1>
        <table>
            <tr><th>Rank</th><th>Player</th><th>Rating</th><th>Record</th></tr>
            {table_rows}
        </table>
        <p>Updates live after every match!</p>
    </body>
    </html>
    ''')

def run_web():
    # Port 8080 is what Replit looks for to trigger the Webview
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()


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

# rank and medals#
@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx):
    if not leaderboard:
        return await ctx.send("❌ The leaderboard is currently empty.")
    
    # Sort by points
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1]["points"], reverse=True)
    
    embed = discord.Embed(
        title="🏆 GRAND ARCHIVE ARENA STANDINGS",
        description="*Current season ranks for Ascent LA Prep*",
        color=0x00d4ff # Neon Blue
    )

    # Top 3 get special formatting
    for i, (uid, stats) in enumerate(sorted_board[:10], 1):
        # Medal Logic
        if i == 1: medal = "🥇 **CHAMPION**"
        elif i == 2: medal = "🥈 **ELITE**"
        elif i == 3: medal = "🥉 **CONTENDER**"
        else: medal = f"**#{i}**"

        # Using a code block inside the value makes the numbers line up perfectly
        stats_line = f"```asc\nRating: {stats['points']} | W: {stats['wins']} L: {stats['losses']}```"
        
        embed.add_field(
            name=f"{medal} — {stats.get('name', 'Unknown')}",
            value=stats_line,
            inline=False
        )

    embed.set_footer(text="Updates live after every reported match.")
    embed.set_thumbnail(url="https://i.imgur.com/your-ga-logo-here.png") # Add a GA icon link here!
    
    await ctx.send(embed=embed)

#rank#

@bot.command(name="rank")
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = str(member.id)
    
    if user_id not in leaderboard:
        return await ctx.send(f"🔍 **{member.display_name}** hasn't recorded any matches in the Arena yet!")

    stats = leaderboard[user_id]
    
    # Safety Math for Win Rate
    total_games = stats['wins'] + stats['losses']
    win_percentage = round((stats['wins'] / total_games) * 100) if total_games > 0 else 0
    
    # Tier Logic (Optional Spiffiness)
    tier = "Bronze"
    if stats['points'] >= 1500: tier = "Grandmaster 🏆"
    elif stats['points'] >= 1200: tier = "Gold 🥇"
    elif stats['points'] >= 1100: tier = "Silver 🥈"

    embed = discord.Embed(
        title=f"⚔️ Arena Profile: {stats.get('name', 'Unknown')}", 
        description=f"**Rank Tier:** {tier}",
        color=0x7289da
    )
    
    # Use display_avatar.url for 2026 compatibility
    embed.set_thumbnail(url=member.display_avatar.url)
    
    embed.add_field(name="Rating", value=f"🛡️ `{stats['points']} Elo`", inline=True)
    embed.add_field(name="Win Rate", value=f"📈 `{win_percentage}%`", inline=True)
    embed.add_field(name="Match Record", value=f"✅ {stats['wins']} | ❌ {stats['losses']} | 🤝 {stats['draws']}", inline=False)
    
    embed.set_footer(text=f"Player ID: {user_id}")
    await ctx.send(embed=embed)


# ---------- Run ----------
if __name__ == "__main__":
    keep_alive()   # This starts the website in the background

TOKEN = os.environ["DISCORD_TOKEN"]
bot.run(TOKEN)
