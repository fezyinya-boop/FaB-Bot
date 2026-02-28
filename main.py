import discord
from discord.ext import commands
import sqlite3
import os
import asyncio

# --- Config & Secrets ---
TOKEN = os.environ["DISCORD_TOKEN"]
LEADERBOARD_CHANNEL_ID = int(os.environ['LEADERBOARD_CHANNEL_ID'])
LEADERBOARD_MSG_ID = 1476843531191717972 
DB_NAME = "arena_tracker.db"

# --- Rank Config ---
RANKS = [
    {"name": "💎 DIAMOND", "min": 1800, "color": 0x00ffff},
    {"name": "📀 PLATINUM", "min": 1600, "color": 0xe5e4e2},
    {"name": "🟡 GOLD", "min": 1400, "color": 0xffd700},
    {"name": "<:rookie:1476994147935322265> SILVER", "min": 1200, "color": 0xc0c0c0},
    {"name": "🟤 BRONZE", "min": 0, "color": 0xcd7f32}
]

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY, name TEXT, points INTEGER, 
                  wins INTEGER, losses INTEGER, streak INTEGER, history TEXT)''')
    conn.commit()
    conn.close()

def get_or_create_user(user_id, name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    if row:
        conn.close()
        return list(row)
    
    c.execute("INSERT INTO users VALUES (?, ?, 1000, 0, 0, 0, '')", (str(user_id), name))
    conn.commit()
    conn.close()
    return [str(user_id), name, 1000, 0, 0, 0, ""]

def update_user_stats(u_id, pts, wins, losses, streak, history):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    hist_str = ",".join(history[-10:])
    c.execute("UPDATE users SET points=?, wins=?, losses=?, streak=?, history=? WHERE user_id=?",
              (pts, wins, losses, streak, hist_str, str(u_id)))
    conn.commit()
    conn.close()

# --- Utility Functions ---
def get_rank_info(points):
    for rank in RANKS:
        if points >= rank["min"]: return rank
    return RANKS[-1]

async def update_player_role(member, points):
    rank_info = get_rank_info(points)
    role = discord.utils.get(member.guild.roles, name=rank_info['name'])
    if role and role not in member.roles:
        all_names = [r['name'] for r in RANKS]
        to_remove = [r for r in member.roles if r.name in all_names]
        await member.remove_roles(*to_remove)
        await member.add_roles(role)

async def refresh_leaderboard(guild):
    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel: return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, points, streak FROM users ORDER BY points DESC LIMIT 10")
    top = c.fetchall()
    conn.close()

    embed = discord.Embed(title="🏆 ARCHIVE ARENA TOP 10", color=0xd4af37)
    desc = ""
    for i, (name, pts, streak) in enumerate(top, 1):
        fire = f"🔥{streak}" if streak >= 3 else ""
        desc += f"{i}. **{name}** - `{pts} RP` {fire}\n"
    embed.description = desc
    embed.set_footer(text="Arena Tracker")
    
    try:
        msg = await channel.fetch_message(LEADERBOARD_MSG_ID)
        await msg.edit(embed=embed)
    except:
        await channel.send(embed=embed)

# --- Match Handling Views ---

class MatchReportingView(discord.ui.View):
    def __init__(self, p1, p2):
        super().__init__(timeout=1800) # 30 Minute Forfeit Timer
        self.p1, self.p2 = p1, p2
        self.reports = {p1.id: None, p2.id: None}

    async def finalize(self, interaction, winner_id):
        w_mem = self.p1 if winner_id == self.p1.id else self.p2
        l_mem = self.p2 if winner_id == self.p1.id else self.p1
        
        w_data = get_or_create_user(w_mem.id, w_mem.display_name)
        l_data = get_or_create_user(l_mem.id, l_mem.display_name)

        r1, r2 = w_data[2], l_data[2]
        pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))

        w_hist = w_data[6].split(",") if w_data[6] else []
        l_hist = l_data[6].split(",") if l_data[6] else []
        w_hist.append("W"); l_hist.append("L")

        update_user_stats(w_mem.id, r1 + pts, w_data[3]+1, w_data[4], w_data[5]+1, w_hist)
        update_user_stats(l_mem.id, r2 - pts, l_data[3], l_data[4]+1, 0, l_hist)

        await update_player_role(w_mem, r1 + pts)
        await update_player_role(l_mem, r2 - pts)
        await refresh_leaderboard(interaction.guild)

        embed = discord.Embed(title="⚔️ MATCH VERIFIED", color=0x2ecc71)
        embed.description = f"**{w_mem.display_name}** defeated **{l_mem.display_name}**\n`+{pts}` RP / `-{pts}` RP"
        embed.set_footer(text="Arena Tracker")
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="I Won", style=discord.ButtonStyle.success, emoji="⚔️")
    async def report_win(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1.id, self.p2.id]: return
        self.reports[interaction.user.id] = interaction.user.id
        await self.check_reports(interaction)

    async def check_reports(self, interaction):
        p1_rep, p2_rep = self.reports[self.p1.id], self.reports[self.p2.id]
        if p1_rep and p2_rep:
            if p1_rep != p2_rep:
                await interaction.response.edit_message(content="⚠️ **DISPUTE!** Both claimed victory. Pinging @Moderator.", view=None)
            else:
                await self.finalize(interaction, p1_rep)
        else:
            await interaction.response.edit_message(content=f"⏳ {interaction.user.name} reported victory. Opponent has 30m to report or forfeit.")

class ChallengeView(discord.ui.View):
    def __init__(self, p1, p2):
        super().__init__(timeout=300)
        self.p1, self.p2 = p1, p2

    @discord.ui.button(label="Accept Match", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.p2.id: return
        await interaction.response.edit_message(content="⚔️ Match Active! Report once finished.", view=MatchReportingView(self.p1, self.p2))

# --- Commands ---
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

@bot.event
async def on_ready():
    init_db()
    print("Arena Tracker Online.")

@bot.command()
async def report(ctx, opponent: discord.Member):
    if opponent == ctx.author: return
    view = ChallengeView(ctx.author, opponent)
    await ctx.send(f"{opponent.mention}, **{ctx.author.name}** challenged you! Do you accept?", view=view)

@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]
    r_info = get_rank_info(pts)
    
    # Progress Bar Logic
    next_rank = next((r for r in reversed(RANKS) if r['min'] > pts), None)
    if next_rank:
        total_needed = next_rank['min'] - r_info['min']
        current_progress = pts - r_info['min']
        percent = min(max(int((current_progress / total_needed) * 10), 0), 10)
        bar = "▰" * percent + "▱" * (10 - percent)
        progress_val = f"{bar} {int((current_progress/total_needed)*100)}% to {next_rank['name']}"
    else:
        progress_val = "▰▰▰▰▰▰▰▰▰▰ **MAX RANK**"

    embed = discord.Embed(title=member.display_name, color=r_info["color"])
    embed.add_field(name="🏆 RATING", value=f"{pts} RP", inline=True)
    embed.add_field(name="🔥 STREAK", value=f"{data[5]} Wins", inline=True)
    
    win_rate = round((data[3] / (data[3] + data[4])) * 100) if (data[3] + data[4]) > 0 else 0
    embed.add_field(name="⚔️ RECORD", value=f"{data[3]}W - {data[4]}L ({win_rate}%)", inline=False)
    embed.add_field(name="🚀 PROGRESS", value=progress_val, inline=False)
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Arena Tracker")
    await ctx.send(embed=embed)

@bot.command()
async def history(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_or_create_user(member.id, member.display_name)
    hist = data[6].split(",") if data[6] else []
    if not hist: return await ctx.send(f"No match history for {member.name}.")
    
    display = "\n".join([f"`{i+1}.` {'🟩 WIN' if r == 'W' else '🟥 LOSS'}" for i, r in enumerate(reversed(hist))])
    embed = discord.Embed(title=f"📜 {member.name}'s History", description=display, color=0x3498db)
    embed.set_footer(text="Arena Tracker")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def settle(ctx, winner: discord.Member, loser: discord.Member):
    """Judge Override to settle disputes."""
    w_data = get_or_create_user(winner.id, winner.display_name)
    l_data = get_or_create_user(loser.id, loser.display_name)
    r1, r2 = w_data[2], l_data[2]
    pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))
    
    w_hist = w_data[6].split(",") if w_data[6] else []
    l_hist = l_data[6].split(",") if l_data[6] else []
    w_hist.append("W"); l_hist.append("L")

    update_user_stats(winner.id, r1+pts, w_data[3]+1, w_data[4], w_data[5]+1, w_hist)
    update_user_stats(loser.id, r2-pts, l_data[3], l_data[4]+1, 0, l_hist)
    
    await update_player_role(winner, r1+pts)
    await update_player_role(loser, r2-pts)
    await refresh_leaderboard(ctx.guild)
    await ctx.send(f"⚖️ **Verdict:** {winner.mention} awarded victory. (+{pts} RP)")

bot.run(TOKEN)
