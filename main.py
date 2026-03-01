import discord
from discord.ext import commands
import sqlite3
import os
import asyncio
import math
import random
from profile_card import make_profile_card, fetch_avatar
from leaderboard_gen import make_leaderboard_image

# --- Config & Secrets ---
TOKEN = os.environ["DISCORD_TOKEN"]
LEADERBOARD_CHANNEL_ID = int(os.environ['LEADERBOARD_CHANNEL_ID'])
MOD_ROLE_ID = 123456789012345678  # <--- Ensure this is your Role ID

# --- Railway-Proof Database Logic ---
# This looks for the variable you just set in the Railway dashboard
# If it doesn't find it, it defaults to a local file (good for testing)
DB_NAME = os.getenv("DB_PATH", "arena_tracker.db")

def init_db():
    # 1. Ensure the directory exists (Crucial for Railway Volumes)
    db_dir = os.path.dirname(DB_NAME)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir)
            print(f"✅ Created directory: {db_dir}")
        except OSError:
            print(f"⚠️ Directory {db_dir} could not be created. Falling back to local.")

    # 2. Connect and create ALL tables in one pass
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # User Statistics & Match History
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, name TEXT, points INTEGER, 
                  wins INTEGER, losses INTEGER, streak INTEGER, history TEXT)''')
    
    # Leaderboard & Bot Configuration
    c.execute('''CREATE TABLE IF NOT EXISTS config 
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # RPG Profile Customization (class_name removed)
    c.execute('''CREATE TABLE IF NOT EXISTS profiles 
                 (user_id TEXT PRIMARY KEY, 
                  title TEXT DEFAULT 'Aspirant', 
                  signature_move TEXT DEFAULT 'None', 
                  embed_color TEXT)''')

    conn.commit()
    conn.close()
    print(f"🚀 Database initialized at: {DB_NAME}")

    

    

# --- Rank Config ---
RANKS = [
    {"name": "<:Diamond:1477427100666433572> DIAMOND", "min": 1800, "color": 0x00ffff},
    {"name": "<:Silver:1477427675067842588> PLATINUM", "min": 1600, "color": 0xe5e4e2},
    {"name": "<:Gold:1477426026945577000> GOLD", "min": 1400, "color": 0xffd700},
    {"name": "<:novice:1477421174249099416> SILVER", "min": 1200, "color": 0xc0c0c0},
    {"name": "<:rookie:1476994147935322265> BRONZE", "min": 0, "color": 0xcd7f32}
]

 #3.DATABASE HELPER (Block 1)
def get_or_create_user(user_id, name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    user = c.fetchone()
    if user is None:
        user = (str(user_id), name, 1000, 0, 0, 0, "")
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", user)
        conn.commit()
    conn.close()
    return user

def update_user_stats(u_id, pts, wins, losses, streak, history):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Logic Fix: If history is somehow still a string, turn it into a list
    if isinstance(history, str):
        history = history.split(",") if history else []
        
    # Keep only the last 10 matches to prevent the DB cell from getting too huge
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


# --- Match Handling Views --- #

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

@bot.command()
async def leaderboard(ctx):
    # This just triggers the same refresh logic manually
    await refresh_leaderboard(ctx.guild)
    await ctx.send("✅ Leaderboard refreshed/posted in the designated channel!")
    
@bot.event
async def on_ready():
    init_db()
    
    # 🔗 Link your existing message to the Database
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    target_id = '1476843531191717972' 
    
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('leaderboard_msg_id', ?)", (target_id,))
    conn.commit()
    conn.close()
    
    print(f"Logged in as {bot.user} | Leaderboard linked to {target_id}")
    print("Arena Tracker Online.")



@bot.command()
async def testlb(ctx):
    # Dummy data to see how the Triple-Font stack looks
    test_players = [
        {"name": "Krona", "pts": 1095, "rank_color": (255, 165, 0)},   # Gold/Orange
        {"name": "Shadow_Player", "pts": 950, "rank_color": (192, 192, 192)}, # Silver
        {"name": "Gothic_Knight", "pts": 820, "rank_color": (205, 127, 50)}, # Bronze
        {"name": "Trial_User", "pts": 450, "rank_color": (100, 100, 100)}     # Grey
    ]

    # Generate the image using the new PIL function
    try:
        image_buf = make_leaderboard_image(test_players)
        
        # Send it as a file
        file = discord.File(fp=image_buf, filename="test_leaderboard.png")
        await ctx.send("📊 **Arena Test Leaderboard**", file=file)
    except Exception as e:
        await ctx.send(f"❌ Error generating leaderboard: {e}")
        

@bot.command()
async def setprofile(ctx, field: str, *, value: str):
    """Usage: !setprofile move Shadow Realm Strike | !setprofile title Shadow King"""
    valid_fields = {
        "move": "signature_move",
        "title": "title",
        "color": "embed_color"
    }
    
    field = field.lower()
    if field not in valid_fields:
        return await ctx.send(f"❌ Invalid field. Use: `move`, `title`, or `color` (hex).")

    if field == "color" and not value.startswith("0x"):
        return await ctx.send("❌ Colors must be in hex format (e.g., `0xff0000`).")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO profiles (user_id) VALUES (?)", (str(ctx.author.id),))
    c.execute(f"UPDATE profiles SET {valid_fields[field]} = ? WHERE user_id = ?", (value, str(ctx.author.id)))
    conn.commit()
    conn.close()
    
    await ctx.send(f"✅ Your **{field}** has been updated to: `{value}`")

@bot.command()
async def cardprofile(ctx, member: discord.Member = None):
    member = member or ctx.author

    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT title, signature_move, embed_color FROM profiles WHERE user_id = ?", (str(member.id),))
    bio = c.fetchone() or ("Aspirant", "None", None)
    conn.close()
    p_title, p_move, p_color = bio

    r_info = get_rank_info(pts)
    next_rank = next((r for r in reversed(RANKS) if r['min'] > pts), None)

    if next_rank:
        total_needed = next_rank['min'] - r_info['min']
        current_progress = pts - r_info['min']
        pct = max(0.0, min(current_progress / total_needed, 1.0))
        next_rank_raw = next_rank['name']
    else:
        pct = 1.0
        next_rank_raw = None

    try:
        hex_color = p_color if p_color else hex(r_info["color"])[2:].zfill(6)
        rank_color = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except:
        rank_color = (230, 160, 30)

    avatar_img = await fetch_avatar(member.display_avatar.url)

    async with ctx.typing():
        buf = make_profile_card(
            display_name=member.display_name,
            p_title=p_title,
            p_move=p_move,
            pts=pts,
            wins=data[3],
            losses=data[4],
            streak=data[5],
            pct=pct,
            current_rank_raw=r_info['name'],
            next_rank_raw=next_rank_raw,
            rank_color=rank_color,
            avatar_img=avatar_img,
        )

    await ctx.send(file=discord.File(buf, filename='profile.png'))


@bot.command()
async def profile(ctx, member: discord.Member = None):
    member = member or ctx.author
    
    # 1. Fetch data from users table
    # Expected: (id, name, pts, wins, losses, streak, history)
    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]

    # 2. Fetch data from profiles table
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT title, signature_move, embed_color FROM profiles WHERE user_id = ?", (str(member.id),))
    bio = c.fetchone() or ("Aspirant", "None", None)
    conn.close()
    p_title, p_move, p_color = bio

    # 3. Rank Logic (The exact !rank sync)
    r_info = get_rank_info(pts) # Gets your current rank dict
    rank_emoji = r_info['name'].split(' ')[0]

    # Find next rank
    next_rank = next((r for r in reversed(RANKS) if r['min'] > pts), None)

    # 4. Progress Bar with Emoji Target
    if next_rank:
        next_emoji = next_rank['name'].split(' ')[0]
        total_needed = next_rank['min'] - r_info['min']
        current_progress = pts - r_info['min']
        
        percent_int = min(max(int((current_progress / total_needed) * 10), 0), 10)
        bar = "▰" * percent_int + "▱" * (10 - percent_int)
        perc_text = int((current_progress / total_needed) * 100)
        
        prog_display = f"{bar} {perc_text}% to {next_emoji}"
    else:
        prog_display = "▰▰▰▰▰▰▰▰▰▰ **MAX RANK REACHED**"

    # 5. Build the Embed
    try:
        color_value = int(p_color, 16) if p_color else r_info["color"]
    except:
        color_value = r_info["color"]

    embed = discord.Embed(title=f"{rank_emoji} {member.display_name}", color=color_value)
    embed.add_field(name="📜 Title", value=f"*{p_title}*", inline=True)
    embed.add_field(name="✨ Signature Move", value=f"**{p_move}**", inline=True)

    total_games = data[3] + data[4]
    wr = round((data[3] / total_games) * 100) if total_games > 0 else 0
    
    embed.add_field(name="🏆 Rating", value=f"`{pts} RP`", inline=True)
    embed.add_field(name="⚔️ Record", value=f"{data[3]}W - {data[4]}L ({wr}%)", inline=True)
    embed.add_field(name="🔥 Streak", value=f"{data[5]} Win Streak", inline=True)
    embed.add_field(name="🚀 Rank Progress", value=prog_display, inline=False)
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Archive Arena | Season 1")

    await ctx.send(embed=embed)


    
    

@bot.command()
@commands.has_permissions(administrator=True)
async def fix_database(ctx):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        # This creates the missing config table
        c.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
        # Also ensure 'streak' column exists in users table just in case
        try:
            c.execute("ALTER TABLE users ADD COLUMN streak INTEGER DEFAULT 0")
        except:
            pass # Already exists
        conn.commit()
        await ctx.send("✅ Database tables patched! You can now use !settle.")
    except Exception as e:
        await ctx.send(f"❌ Error patching database: {e}")
    finally:
        conn.close()

@bot.command()
@commands.has_permissions(administrator=True)
async def sync_rpg(ctx):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        # Create profiles table without class_name
        c.execute('''CREATE TABLE IF NOT EXISTS profiles 
                     (user_id TEXT PRIMARY KEY, 
                      title TEXT DEFAULT 'Aspirant', 
                      signature_move TEXT DEFAULT 'None', 
                      embed_color TEXT)''')
        
        # Safely add columns to users if they are missing
        c.execute("PRAGMA table_info(users)")
        cols = [column[1] for column in c.fetchall()]
        
        if 'streak' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN streak INTEGER DEFAULT 0")
        if 'history' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN history TEXT DEFAULT ''")
            
        conn.commit()
        await ctx.send("✅ **Database Sync Success!** Columns verified and RPG table active.")
    except Exception as e:
        await ctx.send(f"❌ Database Sync Error: {e}")
    finally:
        conn.close()
        

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
    
    # Fetch fresh data from DB (0:id, 1:name, 2:pts, 3:wins, 4:losses, 5:streak)
    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]
    
    # Get current rank info (color, name, min requirements)
    r_info = get_rank_info(pts)
    
    # --- Progress Bar Logic ---
    next_rank = next((r for r in reversed(RANKS) if r['min'] > pts), None)
    if next_rank:
        total_needed = next_rank['min'] - r_info['min']
        current_progress = pts - r_info['min']
        # Calculate percentage (0-10 for the bar, 0-100 for the text)
        percent = min(max(int((current_progress / total_needed) * 10), 0), 10)
        bar = "▰" * percent + "▱" * (10 - percent)
        progress_val = f"{bar} {int((current_progress/total_needed)*100)}% to {next_rank['name']}"
    else:
        progress_val = "▰▰▰▰▰▰▰▰▰▰ **MAX RANK**"

    # --- Build the Embed ---
    embed = discord.Embed(title=f"战 {member.display_name}", color=r_info["color"])
    embed.add_field(name="🏆 RATING", value=f"{pts} RP", inline=True)
    embed.add_field(name="🔥 STREAK", value=f"{data[5]} Wins", inline=True)
    
    # Win Rate Calc: data[3] is wins, data[4] is losses
    total_games = data[3] + data[4]
    win_rate = round((data[3] / total_games) * 100) if total_games > 0 else 0
    
    embed.add_field(name="⚔️ RECORD", value=f"{data[3]}W - {data[4]}L ({win_rate}%)", inline=False)
    embed.add_field(name="🚀 PROGRESS", value=progress_val, inline=False)
    
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def history(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_or_create_user(member.id, member.display_name)
    raw_hist = data[6].split(",") if data[6] else []
    
    if not raw_hist: 
        return await ctx.send(f"No match history for {member.display_name}.")
    
    # --- FIXED INDENTATION START ---
    display = ""
    for entry in reversed(raw_hist):
        parts = entry.split(":")
        
        # Check if the entry has the modern format (Result:Opponent:Points)
        if len(parts) >= 3: 
            res, opp, rp = parts[0], parts[1], parts[2]
            circle = "🟢" if res == "W" else "🔴"
            # Logic for the prefix (+ or -)
            prefix = "+" if res == "W" else "-"
            display += f"{circle} **{res}** vs {opp} (`{prefix}{rp} RP`)\n"
            
        # Fallback for old/legacy entries
        elif len(parts) == 1 and parts[0]: 
            res = parts[0]
            circle = "🟢" if res == "W" else "🔴"
            display += f"{circle} **{res}** (Legacy Match)\n"

    if not display:
        display = "No recent matches recorded."
        
    # --- FIXED INDENTATION END ---

    embed = discord.Embed(title=f"📜 {member.display_name}'s History", description=display, color=0x3498db)
    embed.set_footer(text="Last 10 Matches")
    await ctx.send(embed=embed)

async def refresh_leaderboard(guild):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. Fetch Top 10
    c.execute("SELECT name, points, streak FROM users ORDER BY points DESC LIMIT 10")
    top_players = c.fetchall()
    
    c.execute("SELECT value FROM config WHERE key = 'leaderboard_msg_id'")
    row = c.fetchone()
    saved_msg_id = int(row[0]) if row else None
    conn.close()

    embed = discord.Embed(title="⚔️ ARCHIVE ARENA: TOP 10", color=0xFFD700)
    
    leaderboard_text = ""
    for i, (name, pts, streak) in enumerate(top_players, 1):
        # Determine Rank
        emblem_only = "💀" # Default if no rank found
        for rank in reversed(RANKS):
            if pts >= rank['min']:
                # This splits "<:rookie:123> BRONZE" and takes only the first part
                emblem_only = rank['name'].split(' ')[0]
                break
        
        # Fire Emoji for 3+ Win Streak
        streak_flare = " 🔥" if streak >= 3 else ""
        
        # Format: 1. <:rookie:123> Name 🔥 — 1200 RP
        leaderboard_text += f"**{i}.** {emblem_only} **{name}**{streak_flare} — `{pts} RP`\n"

    embed.description = leaderboard_text or "The arena is silent... post a match to begin."
    embed.set_footer(text="Updates automatically | Use !rank to see your progress")

    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel: return

    try:
        if saved_msg_id:
            msg = await channel.fetch_message(saved_msg_id)
            await msg.edit(embed=embed)
        else:
            new_msg = await channel.send(embed=embed)
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO config VALUES ('leaderboard_msg_id', ?)", (str(new_msg.id),))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Leaderboard Refresh Error: {e}")


    

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
    await refresh_leaderboard(ctx.guild)

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
