import discord
from discord.ext import commands
import json
import os

# This pulls from your Replit Secrets
LEADERBOARD_CHANNEL_ID = int(os.environ['LEADERBOARD_CHANNEL_ID'])

# This you hard-code manually after you get the ID from Discord
LEADERBOARD_MSG_ID = 1476843531191717972  # Replace this with your actual Message ID


# --- Data Management ---
def load_data():
    if os.path.exists('leaderboard.json'):
        with open('leaderboard.json', 'r') as f:
            return json.load(f)
    return {}

def save_data():
    with open('leaderboard.json', 'w') as f:
        json.dump(leaderboard, f, indent=4)

leaderboard = load_data()

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- RANK & STREAK CONFIG ---
RANKS = [
    {"name": "💎 DIAMOND", "min": 1800, "color": 0x00ffff},
    {"name": "📀 PLATINUM", "min": 1600, "color": 0xe5e4e2},
    {"name": "🟡 GOLD", "min": 1400, "color": 0xffd700},
    {"name": "⚪ SILVER", "min": 1200, "color": 0xc0c0c0},
    {"name": "🟤 BRONZE", "min": 0, "color": 0xcd7f32}
]

def get_rank_info(points):
    for rank in RANKS:
        if points >= rank["min"]: return rank
    return RANKS[-1]


async def update_live_leaderboard(guild):
    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel: return

    # Sort players by points
    top_10 = sorted(leaderboard.items(), key=lambda x: x[1]['points'], reverse=True)[:10]
    
    embed = discord.Embed(title="🏆 ARCHIVE ARENA TOP 10", color=0xd4af37)
    
    description = ""
    for i, (uid, data) in enumerate(top_10, 1):
        rank_info = get_rank_info(data['points'])
        streak = f"🔥{data.get('streak', 0)}" if data.get('streak', 0) >= 3 else ""
        description += f"{i}. {rank_info['id']} **{data['name']}** - `{data['points']} RP` {streak}\n"
    
    embed.description = description
    embed.set_footer(text="Updates automatically after every match.")

    # Try to edit existing message, otherwise send new one
    try:
        msg = await channel.fetch_message(LEADERBOARD_MSG_ID)
        await msg.edit(embed=embed)
    except:
        new_msg = await channel.send(embed=embed)
        # Record this new_msg.id in your code/file so it can edit it next time!


async def update_player_role(member, points):
    rank_info = get_rank_info(points)
    # Find the role in the server that matches the Rank Name
    role = discord.utils.get(member.guild.roles, name=rank_info['name'])
    
    if role and role not in member.roles:
        # Remove old rank roles first
        all_rank_names = [r['name'] for r in RANKS]
        roles_to_remove = [r for r in member.roles if r.name in all_rank_names]
        await member.remove_roles(*roles_to_remove)
        
        # Add new rank role
        await member.add_roles(role)

# --- MATCH VERIFICATION VIEW ---
class ReportView(discord.ui.View):
    def __init__(self, winner, loser):
        super().__init__(timeout=600) # 10 Minute Auto-Forfeit Timer
        self.winner = winner
        self.loser = loser

    async def on_timeout(self):
        # If the loser ignores the button for 10 mins, it auto-confirms
        await self.process_match(is_timeout=True)

    @discord.ui.button(label="Confirm Win", style=discord.ButtonStyle.success, emoji="⚔️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.loser.id:
            return await interaction.response.send_message("❌ Only the loser can confirm this.", ephemeral=True)
        await self.process_match(interaction=interaction)

    async def process_match(self, interaction=None, is_timeout=False):
        w_id, l_id = str(self.winner.id), str(self.loser.id)
        
        # Ensure players exist in data
        for uid, mem in [(w_id, self.winner), (l_id, self.loser)]:
            leaderboard.setdefault(uid, {"name": mem.display_name, "points": 1000, "wins": 0, "losses": 0, "streak": 0})

        # Calculate Rank Before Match
        old_rank = get_rank_info(leaderboard[w_id]['points'])

        # Elo Math
        r1, r2 = leaderboard[w_id]['points'], leaderboard[l_id]['points']
        pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))

        # Update Stats
        leaderboard[w_id]['points'] += pts
        leaderboard[l_id]['points'] -= pts
        leaderboard[w_id]['wins'] += 1
        leaderboard[l_id]['losses'] += 1
        leaderboard[w_id]['streak'] += 1
        leaderboard[l_id]['streak'] = 0 
        save_data()

                # 1. Update the player's Discord roles based on their new RP
        await update_player_role(self.winner, leaderboard[w_id]['points'])
        await update_player_role(self.loser, leaderboard[l_id]['points'])
        
        # 2. Update the live leaderboard pinned message
        await update_live_leaderboard(self.winner.guild)


        # Check for Rank Up
        new_rank = get_rank_info(leaderboard[w_id]['points'])
        rank_up_msg = f"\n🆙 **RANK UP:** {self.winner.mention} ascended to **{new_rank['name']}**!" if new_rank['name'] != old_rank['name'] else ""

        # Build Embed
        title = "⚔️ MATCH VERIFIED" if not is_timeout else "⏰ AUTO-VERIFIED (TIMEOUT)"
        streak_msg = f"\n🔥 **On a {leaderboard[w_id]['streak']} win streak!**" if leaderboard[w_id]['streak'] >= 3 else ""
        
        embed = discord.Embed(title=title, color=new_rank["color"])
        embed.description = f"**{self.winner.display_name}** defeated **{self.loser.display_name}**\n`+{pts}` RP / `-{pts}` RP{streak_msg}{rank_up_msg}"
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            # This handles the auto-timeout edit
            pass # You'd need a reference to the message here if you want to edit it on timeout

@bot.command()
async def report(ctx, opponent: discord.Member):
    if opponent == ctx.author:
        return await ctx.send("❌ You can't report a win against yourself.")
    
    view = ReportView(winner=ctx.author, loser=opponent)
    embed = discord.Embed(
        title="📝 Match Pending Verification",
        description=f"{opponent.mention}, **{ctx.author.display_name}** claims they won.\nClick the button below to confirm. (Expires in 10 mins)",
        color=0x7289da
    )
    await ctx.send(embed=embed, view=view)


# --- Commands ---

@bot.command()
async def report(ctx, opponent: discord.Member):
    if opponent == ctx.author:
        return await ctx.send("❌ You can't fight yourself, Champion.")
    
    view = ReportView(ctx.author, opponent)
    embed = discord.Embed(
        title="PENDING VERIFICATION",
        description=f"{ctx.author.mention} claims victory over {opponent.mention}.\n\n**{opponent.display_name}**, please confirm.",
        color=0x00d4ff
    )
    await ctx.send(embed=embed, view=view)

@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    uid = str(member.id)
    
    # Check if they exist, if not, give them "Starter" stats instead of an error
    if uid not in leaderboard:
        user_data = {
            "name": member.display_name,
            "points": 1000,
            "wins": 0,
            "losses": 0,
            "streak": 0
        }
    else:
        user_data = leaderboard[uid]

    pts = user_data['points']
    # Rest of your rank code stays the same...


    data = leaderboard[uid]
    pts = data['points']
    rank_info = get_rank_info(pts)
    
    # Calculate progress to next rank
    next_rank = next((r for r in reversed(RANKS) if r['min'] > pts), None)
    if next_rank:
        total_needed = next_rank['min'] - rank_info['min']
        current_progress = pts - rank_info['min']
        percent = min(max(int((current_progress / total_needed) * 10), 0), 10)
        bar = "▰" * percent + "▱" * (10 - percent)
        progress_str = f"\n`{bar}` {int((current_progress/total_needed)*100)}% to {next_rank['name']}"
    else:
        progress_str = "\n`▰▰▰▰▰▰▰▰▰▰` **MAX RANK**"
    
                    embed = discord.Embed(title=member.display_name, color=rank_info["color"])
    
    # ROW 1: Rank and Points
    embed.add_field(name="🛡️ TIER", value=f"{rank_info['id']} {rank_info['name']}", inline=True)
    embed.add_field(name="🏆 RATING", value=f"{pts} RP", inline=True)
    
    # ROW 2: Record and Streak
    win_rate = round((user_data['wins'] / (user_data['wins'] + user_data['losses'])) * 100) if (user_data['wins'] + user_data['losses']) > 0 else 0
    embed.add_field(name="⚔️ RECORD", value=f"{user_data['wins']}W - {user_data['losses']}L\n`{win_rate}% WR`", inline=True)
    embed.add_field(name="🔥 STREAK", value=f"{user_data.get('streak', 0)} Wins", inline=True)
    
    # ROW 3: Progress Bar (Set to inline=False so it stretches across the bottom)
    embed.add_field(name="🚀 RANK PROGRESS", value=f"\n{bar} {int((current_progress/total_needed)*100)}% to {next_rank['name']}", inline=False)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Arena Keeper")

    await ctx.send(embed=embed)







@bot.command()
@commands.has_permissions(administrator=True)
async def force_sync(ctx):
    """Forces Replit to write the leaderboard to the actual disk."""
    try:
        with open('leaderboard.json', 'w') as f:
            json.dump(leaderboard, f, indent=4)
            f.flush()
            os.fsync(f.fileno()) # The 'Hard Commit'
        await ctx.send("💎 **The Archive has been hard-synced to disk.**")
    except Exception as e:
        await ctx.send(f"❌ **Sync Failed:** {e}")

    
TOKEN = os.environ["DISCORD_TOKEN"]
bot.run(TOKEN)
