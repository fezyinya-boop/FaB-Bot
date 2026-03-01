import discord
from discord.ext import commands
import sqlite3
import os
import asyncio
import math
import random 

# --- Config & Secrets ---
TOKEN = os.environ["DISCORD_TOKEN"]
LEADERBOARD_CHANNEL_ID = int(os.environ['LEADERBOARD_CHANNEL_ID'])
LEADERBOARD_MSG_ID = 1476843531191717972 
MOD_ROLE_ID = 123456789012345678  # <--- Ensure this is your Role ID
DB_NAME = "arena_tracker.db"

# --- Rank Config ---
RANKS = [
    {"name": "<:Diamond:1477427100666433572> DIAMOND", "min": 1800, "color": 0x00ffff},
    {"name": "<:Silver:1477427675067842588> PLATINUM", "min": 1600, "color": 0xe5e4e2},
    {"name": "<:Gold:1477426026945577000> GOLD", "min": 1400, "color": 0xffd700},
    {"name": "<:novice:1477421174249099416> SILVER", "min": 1200, "color": 0xc0c0c0},
    {"name": "<:rookie:1476994147935322265> BRONZE", "min": 0, "color": 0xcd7f32}
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
    
    # This splits the name by spaces and takes the last part
    # e.g., "<:novice:ID> SILVER" becomes "SILVER"
    clean_role_name = rank_info['name'].split()[-1]
    
    role = discord.utils.get(member.guild.roles, name=clean_role_name)
    
    if role and role not in member.roles:
        # Create a list of all possible rank names (the plain text parts) to remove
        all_rank_names = [r['name'].split()[-1] for r in RANKS]
        
        # Identify which roles the user has that are arena ranks
        to_remove = [r for r in member.roles if r.name in all_rank_names]
        
        await member.remove_roles(*to_remove)
        await member.add_roles(role)

@bot.command()
async def ranks(ctx):
    """Displays the RP requirements and custom icons for all ranks."""
    embed = discord.Embed(
        title="📊 ARCHIVE ARENA RANKING TIERS",
        description="Earn RP by winning duels to climb the ladder!",
        color=0xffffff  # Neutral white for the full list
    )

    # We build the list from highest to lowest
    rank_list = ""
    for r in RANKS:
        rank_list += f"{r['name']} — **{r['min']}+ RP**\n"

    embed.add_field(name="Current Tiers", value=rank_list, inline=False)
    
    # Adding a little tip at the bottom
    embed.set_footer(text="Higher ranks earn more prestige in the Leaderboard!")
    
    await ctx.send(embed=embed)
    
        

async def update_leaderboard():
    """Updates the pinned leaderboard message with custom rank emojis."""
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel:
        return

    # Sort players by RP descending
    sorted_players = sorted(player_data.items(), key=lambda x: x[1]['points'], reverse=True)
    top_10 = sorted_players[:10]

    embed = discord.Embed(
        title="🏆 ARENA LEADERBOARD - TOP 10 🏆",
        description="The top 10 warriors in the Archive Arena.",
        color=0x2ecc71
    )

    lb_text = ""
    for i, (user_id, data) in enumerate(top_10, 1):
        user = bot.get_user(int(user_id))
        name = user.display_name if user else f"Unknown({user_id})"
        
        # Get the rank info to pull the custom emoji
        rank_info = get_rank_info(data['points'])
        rank_emoji = rank_info['name'].split()[0]  # Grabs the <:emoji:ID> part
        
        lb_text += f"{i}. {rank_emoji} **{name}** — {data['points']} RP\n"

    embed.description = lb_text if lb_text else "No matches played yet."
    embed.set_footer(text="Last 10 Matches") # Matches your preferred footer

    # Logic to edit the existing message or send a new one
    # (Assuming you have 'leaderboard_msg_id' stored)
    global leaderboard_msg_id
    if leaderboard_msg_id:
        try:
            msg = await channel.fetch_message(leaderboard_msg_id)
            await msg.edit(embed=embed)
        except:
            msg = await channel.send(embed=embed)
            leaderboard_msg_id = msg.id
    else:
        msg = await channel.send(embed=embed)
        leaderboard_msg_id = msg.id


# --- Match Handling Views ---

class MatchReportingView(discord.ui.View):
    def __init__(self, p1, p2):
        super().__init__(timeout=1800)
        self.p1, self.p2 = p1, p2
        self.reports = {p1.id: None, p2.id: None}
        self.report_p1.label = f"{p1.display_name} Won"
        self.report_p2.label = f"{p2.display_name} Won"

    async def finalize(self, interaction, winner_id):
        w_mem = self.p1 if winner_id == self.p1.id else self.p2
        l_mem = self.p2 if winner_id == self.p1.id else self.p1
        
        w_data = get_or_create_user(w_mem.id, w_mem.display_name)
        l_data = get_or_create_user(l_mem.id, l_mem.display_name)

        r1, r2 = w_data[2], l_data[2]
        pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))

        w_hist = w_data[6].split(",") if w_data[6] else []
        l_hist = l_data[6].split(",") if l_data[6] else []
        
        w_hist.append(f"W:{l_mem.display_name}:{pts}")
        l_hist.append(f"L:{w_mem.display_name}:{pts}")

        update_user_stats(w_mem.id, r1 + pts, w_data[3]+1, w_data[4], w_data[5]+1, w_hist)
        update_user_stats(l_mem.id, r2 - pts, l_data[3], l_data[4]+1, 0, l_hist)

        await update_player_role(w_mem, r1 + pts)
        await update_player_role(l_mem, r2 - pts)
        await refresh_leaderboard(interaction.guild)

        rank_info = get_rank_info(r1 + pts)
        embed = discord.Embed(title="⚔️ MATCH VERIFIED", color=rank_info["color"])
        streak_msg = f"\n🔥 **On a {w_data[5]+1} win streak!**" if w_data[5]+1 >= 3 else ""
        
        embed.description = f"**{w_mem.display_name}** defeated **{l_mem.display_name}**"
        embed.add_field(name="RESULTS", value=f"📈 **{w_mem.display_name}**: `+{pts} RP`\n📉 **{l_mem.display_name}**: `-{pts} RP`{streak_msg}", inline=False)
        embed.set_footer(text="Arena Tracker • Match Finalized")
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="Player A Won", style=discord.ButtonStyle.success, emoji="⚔️")
    async def report_p1(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1.id, self.p2.id]: return
        self.reports[interaction.user.id] = self.p1.id
        await self.check_reports(interaction)

    @discord.ui.button(label="Player B Won", style=discord.ButtonStyle.success, emoji="⚔️")
    async def report_p2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1.id, self.p2.id]: return
        self.reports[interaction.user.id] = self.p2.id
        await self.check_reports(interaction)

    async def check_reports(self, interaction):
        p1_rep, p2_rep = self.reports[self.p1.id], self.reports[self.p2.id]
        if p1_rep and p2_rep:
            if p1_rep != p2_rep:
                embed = discord.Embed(
                    title="⚠️ MATCH DISPUTE",
                    description=f"**{self.p1.display_name}** and **{self.p2.display_name}** reported different winners.\n\nAutomated tracking is paused. A <@&{MOD_ROLE_ID}> must resolve this manually.",
                    color=0xe74c3c
                )
                embed.set_footer(text="Arena Tracker • Dispute Phase")
                await interaction.response.edit_message(content=f"<@&{MOD_ROLE_ID}>", embed=embed, view=None)
            else:
                await self.finalize(interaction, p1_rep)
        else:
            await interaction.response.edit_message(content=f"⏳ **{interaction.user.display_name}** reported. Waiting for opponent to verify (30m remains)...")

class ChallengeView(discord.ui.View):
    def __init__(self, p1, p2):
        super().__init__(timeout=300)
        self.p1, self.p2 = p1, p2

    @discord.ui.button(label="Accept Match", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.p2.id: return
        embed = discord.Embed(
            title="⚔️ MATCH ACTIVE",
            description=f"Match started between **{self.p1.display_name}** and **{self.p2.display_name}**.\n\nOnce finished, **both** players must report the winner below.",
            color=0x3498db
        )
        embed.set_footer(text="Arena Tracker • Reporting Phase")
        await interaction.response.edit_message(content=None, embed=embed, view=MatchReportingView(self.p1, self.p2))

# --- Commands ---
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

@bot.event
async def on_ready():
    init_db()
    print("Arena Tracker Online.")

@bot.command()
async def rules(ctx):
    """Displays the official Archive Arena rules and ranking system."""
    # Build the Rank strings dynamically from the RANKS list
    rank_summary = ""
    for r in RANKS:
        rank_summary += f"• {r['name']}: {r['min']}+ RP\n"

    embed = discord.Embed(
        title="🛡️ ARCHIVE ARENA OFFICIAL RULES",
        description=(
            "Welcome to the Arena. To maintain a fair and competitive environment, "
            "all players must adhere to the following guidelines:\n\n"
            "**1. Match Reporting**\n"
            "Both players must report the outcome immediately after a match. "
            "Intentional false reporting will result in a rank reset or ban.\n\n"
            "**2. Disputes**\n"
            "If a dispute occurs, the automated system pauses. Post a screenshot of your "
            "victory in this channel and wait for a moderator to settle it.\n\n"
            "**3. Sportsmanship**\n"
            "Toxic behavior, stalling, or 'counter-picking' outside of allowed "
            "parameters is prohibited.\n\n"
            
        ),
        color=0x7289da
    )
    
    embed.add_field(
        name="📊 RANKING SYSTEM",
        value=rank_summary,
        inline=False
    )
    
    embed.set_footer(text="Play Fair, Duel Hard")
    await ctx.send(embed=embed)


    

@bot.command(aliases=['challenge'])
async def duel(ctx, opponent: discord.Member):
    """Issues a formal challenge to another player."""
    if opponent == ctx.author: 
        return await ctx.send("❌ You can't duel yourself! (As much as we all love a good practice session).")
    
    if opponent.bot:
        return await ctx.send("❌ The bots are currently on strike and refuse to duel mortals.")

    view = ChallengeView(ctx.author, opponent)
    embed = discord.Embed(
        title="⚔️ CHALLENGE ISSUED",
        description=f"{opponent.mention}, **{ctx.author.display_name}** has challenged you to a duel!\n\nDo you accept your fate?",
        color=0x7289da
    )
    embed.set_footer(text="Arena Tracker • Awaiting Response")
    await ctx.send(embed=embed, view=view)


@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]
    r_info = get_rank_info(pts)
    
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
    raw_hist = data[6].split(",") if data[6] else []
    if not raw_hist: return await ctx.send(f"No match history for {member.display_name}.")
    
    display = ""
    for entry in reversed(raw_hist):
        parts = entry.split(":")
        if len(parts) == 3: 
            res, opp, rp = parts
            circle = "🟢" if res == "W" else "🔴"
            arrow = "📈" if res == "W" else "📉"
            display += f"{circle} **{res}** vs {opp} ({arrow} `{rp} RP`)\n"
        else: 
            res = parts[0]
            circle = "🟢" if res == "W" else "🔴"
            display += f"{circle} **{res}** (Match data unavailable)\n"

    embed = discord.Embed(title=f"📜 {member.display_name}'s History", description=display, color=0x3498db)
    # FOOTER UPDATED: Removed Arena Tracker
    embed.set_footer(text="Last 10 Matches")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def settle(ctx, winner: discord.Member, loser: discord.Member):
    w_data = get_or_create_user(winner.id, winner.display_name)
    l_data = get_or_create_user(loser.id, loser.display_name)
    r1, r2 = w_data[2], l_data[2]
    pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))
    
    w_hist = w_data[6].split(",") if w_data[6] else []
    l_hist = l_data[6].split(",") if l_data[6] else []
    
    w_hist.append(f"W:{loser.display_name}:{pts}")
    l_hist.append(f"L:{winner.display_name}:{pts}")

    update_user_stats(winner.id, r1+pts, w_data[3]+1, w_data[4], w_data[5]+1, w_hist)
    update_user_stats(loser.id, r2-pts, l_data[3], l_data[4]+1, 0, l_hist)
    
    await update_player_role(winner, r1+pts)
    await update_player_role(loser, r2-pts)
    await refresh_leaderboard(ctx.guild)
    
    embed = discord.Embed(title="⚖️ JUDGE VERDICT", color=0xe74c3c)
    embed.description = f"**{winner.display_name}** awarded victory over **{loser.display_name}**."
    embed.add_field(name="RP SHIFT", value=f"📈 {winner.display_name}: `+{pts}`\n📉 {loser.display_name}: `-{pts}`")
    # FOOTER UPDATED: Removed Arena Tracker
    embed.set_footer(text="Dispute Resolved")
    await ctx.send(embed=embed)

# --- Tournament Globals ---
tournament_players = []  # List of member objects
tournament_active = False
tournament_bracket = []  # List of match dictionaries

@bot.command()
@commands.has_permissions(manage_messages=True)
async def tourney_open(ctx):
    global tournament_players, tournament_active
    tournament_players = []
    tournament_active = True
    
    embed = discord.Embed(
        title="🛡️ TOURNAMENT REGISTRATION OPEN",
        description="Click the button below to enter the Archive Arena Tournament!\n\n**Participants:** 0",
        color=0x2ecc71
    )
    
    view = discord.ui.View(timeout=None)
    button = discord.ui.Button(label="Join Tournament", style=discord.ButtonStyle.primary, emoji="⚔️")

    async def join_callback(interaction):
        if interaction.user in tournament_players:
            return await interaction.response.send_message("You're already in!", ephemeral=True)
        
        tournament_players.append(interaction.user)
        embed.description = f"Click the button below to enter the Archive Arena Tournament!\n\n**Participants:** {len(tournament_players)}\n" + \
                            ", ".join([p.display_name for p in tournament_players])
        await interaction.message.edit(embed=embed)
        await interaction.response.send_message("Registered!", ephemeral=True)

    button.callback = join_callback
    view.add_item(button)
    await ctx.send(embed=embed, view=view)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def tourney_start(ctx):
    global tournament_bracket, tournament_players
    if len(tournament_players) < 2:
        return await ctx.send("Not enough players to start!")

    # 1. Seed by RP (High vs Low)
    player_data = []
    for p in tournament_players:
        data = get_or_create_user(p.id, p.display_name)
        player_data.append((p, data[2])) # (Member, RP)
    
    player_data.sort(key=lambda x: x[1], reverse=True)
    sorted_players = [p[0] for p in player_data]

    # 2. Build Initial Bracket (Standard Seeding)
    bracket_size = 1 << (len(sorted_players) - 1).bit_length() # Next power of 2
    tournament_bracket = []
    
    # Fill with "Byes" if not power of 2
    while len(sorted_players) < bracket_size:
        sorted_players.append(None)

    # Pair them: 1st vs Last, 2nd vs 2nd Last
    for i in range(bracket_size // 2):
        p1 = sorted_players[i]
        p2 = sorted_players[-(i+1)]
        tournament_bracket.append({"p1": p1, "p2": p2, "winner": None})

    # 3. Display Bracket
    embed = discord.Embed(title="🏟️ TOURNAMENT BRACKET GENERATED", color=0x3498db)
    match_str = ""
    for i, m in enumerate(tournament_bracket, 1):
        name1 = m['p1'].display_name if m['p1'] else "BYE"
        name2 = m['p2'].display_name if m['p2'] else "BYE"
        match_str += f"**Match {i}:** {name1} vs {name2}\n"
        
        # Auto-advance Byes
        if m['p2'] is None: m['winner'] = m['p1']
        if m['p1'] is None: m['winner'] = m['p2']

    embed.description = match_str
    pings = " ".join([p.mention for p in tournament_players if p])
    await ctx.send(content=pings, embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def tourney_reward(ctx, first: discord.Member, second: discord.Member, third: discord.Member):
    # Fixed Lump Sum Rewards
    rewards = {first: 150, second: 75, third: 30}
    
    summary = ""
    for member, amt in rewards.items():
        data = get_or_create_user(member.id, member.display_name)
        new_pts = data[2] + amt
        
        # Manual DB Update for rewards
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE users SET points=? WHERE user_id=?", (new_pts, str(member.id)))
        conn.commit()
        conn.close()
        
        summary += f"🥇" if amt == 150 else "🥈" if amt == 75 else "🥉"
        summary += f" **{member.display_name}**: +{amt} RP (Total: `{new_pts}`)\n"
        await update_player_role(member, new_pts)

    embed = discord.Embed(title="🎊 TOURNAMENT RESULTS", description=summary, color=0xf1c40f)
    embed.set_footer(text="Dispute Resolved") # Using your requested footer style
    await ctx.send(embed=embed)
    await refresh_leaderboard(ctx.guild)

# --- Tournament Management Block ---

@bot.command()
@commands.has_permissions(manage_messages=True)
async def tourney_add(ctx, member: discord.Member):
    """Manually forces a player into the tournament roster."""
    global tournament_players, tournament_active
    if not tournament_active:
        return await ctx.send("❌ No tournament is currently open. Use `!tourney_open` first.")
    
    if member in tournament_players:
        return await ctx.send(f"⚠️ {member.display_name} is already on the list.")

    tournament_players.append(member)
    await ctx.send(f"✅ **{member.display_name}** has been manually added to the roster.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def tourney_kick(ctx, member: discord.Member):
    """Removes a player from the tournament at any stage (Registration or Active)."""
    global tournament_players
    if member in tournament_players:
        tournament_players.remove(member)
        await ctx.send(f"✅ **{member.display_name}** has been removed from the tournament.")
    else:
        await ctx.send(f"❌ {member.display_name} isn't in the tournament list.")

@bot.command()
async def tourney_list(ctx):
    """Shows all players currently in the tournament."""
    if not tournament_active:
        return await ctx.send("No tournament is currently active.")
    
    if not tournament_players:
        return await ctx.send("The tournament is open, but no one has joined yet.")

    player_list = "\n".join([f"• {p.display_name}" for p in tournament_players])
    embed = discord.Embed(
        title="📝 CURRENT ROSTER",
        description=player_list,
        color=0x3498db
    )
    embed.set_footer(text="Last 10 Matches")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def tourney_end(ctx):
    """Kills the current tournament session and wipes all data."""
    global tournament_players, tournament_active, tournament_bracket
    
    if not tournament_active:
        return await ctx.send("There is no active tournament to end.")

    tournament_players = []
    tournament_bracket = []
    tournament_active = False
    
    embed = discord.Embed(
        title="🏁 TOURNAMENT CONCLUDED",
        description="The tournament session has been killed. All registration data and brackets have been wiped.",
        color=0x95a5a6
    )
    embed.set_footer(text="Dispute Resolved")
    await ctx.send(embed=embed)

    
    

bot.run(TOKEN)
