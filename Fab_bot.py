import discord
from discord.ext import commands
import json
import os

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

# --- Match Verification System ---
class ReportView(discord.ui.View):
    def __init__(self, winner, loser):
        super().__init__(timeout=600) # 10 minute window
        self.winner = winner
        self.loser = loser

    @discord.ui.button(label="Confirm Win", style=discord.ButtonStyle.success, emoji="⚔️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.loser.id:
            await interaction.response.send_message("❌ Only the opponent can verify this result.", ephemeral=True)
            return

        # Initialize players
        w_id, l_id = str(self.winner.id), str(self.loser.id)
        for uid, mem in [(w_id, self.winner), (l_id, self.loser)]:
            leaderboard.setdefault(uid, {"name": mem.display_name, "points": 1000, "wins": 0, "losses": 0})

        # Elo Math
        r1, r2 = leaderboard[w_id]['points'], leaderboard[l_id]['points']
        k, expected = 32, 1 / (1 + 10 ** ((r2 - r1) / 400))
        pts = round(k * (1 - expected))

        # Update
        leaderboard[w_id]['points'] += pts
        leaderboard[l_id]['points'] -= pts
        leaderboard[w_id]['wins'] += 1
        leaderboard[l_id]['losses'] += 1
        save_data()

        embed = discord.Embed(title="⚔️ MATCH VERIFIED", color=0xd4af37)
        embed.description = f"**{self.winner.display_name}** defeated **{self.loser.display_name}**\n\nGain: `+{pts}` RP | Loss: `-{pts}` RP"
        embed.set_thumbnail(url=self.winner.display_avatar.url)
        
        await interaction.response.edit_message(embed=embed, view=None)

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
    
    if uid not in leaderboard:
        return await ctx.send(f"❌ {member.display_name} has no record in the Archive.")

    data = leaderboard[uid]
    total = data['wins'] + data['losses']
    wr = round((data['wins'] / total) * 100) if total > 0 else 0

    embed = discord.Embed(title="PLAYER PROFILE", color=0xd4af37)
    embed.set_author(name="Archive Arena", icon_url=bot.user.avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🏆 RATING", value=f"`{data['points']}`", inline=True)
    embed.add_field(name="⚔️ RECORD", value=f"`{data['wins']}W - {data['losses']}L`", inline=True)
    embed.add_field(name="📊 WIN RATE", value=f"`{wr}%`", inline=True)
    embed.set_footer(text="Ascent LA 2026")
    
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
