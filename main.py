import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import asyncio
from profile_card import make_profile_card, fetch_avatar
from flask import Flask, jsonify
from flask_cors import CORS
from threading import Thread
from tabulate import tabulate 
import urllib.parse
import aiohttp

# --- Config & Secrets ---
TOKEN = os.environ["DISCORD_TOKEN"]
LEADERBOARD_CHANNEL_ID = int(os.environ['LEADERBOARD_CHANNEL_ID'])
MOD_ROLE_ID = 1477213439586996285 # <--- Ensure this is your Role ID
GUILD_ID = int(os.getenv("GUILD_ID", 0))
DUEL_CHANNEL_ID = 1477881887601983669
GATCG_API_BASE = "https://api.gatcg.com"

# --- Railway-Proof Database Logic ---
# This looks for the variable you just set in the Railway dashboard
# If it doesn't find it, it defaults to a local file (good for testing)
DB_NAME = os.getenv("DB_PATH", "arena_tracker.db")

def get_conn():
    """Centralized SQLite connection helper (WAL + timeout for Railway)."""
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        # Pragmas are best-effort; ignore if environment disallows.
        pass
    return conn


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
    conn = get_conn()
    c = conn.cursor()
    # Pragmas help reduce 'database is locked' under concurrency
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=NORMAL')

    meta_decks = [
        # S Tier
        ('Rai', 'S'),
        ('Silvie', 'S'),
        # A Tier
        ('Lorraine', 'A'),
        ('Mordred', 'A'),
        ('Alyndra', 'A'),
        # B Tier
        ('Tristan', 'B'),
        ('Diana', 'B'),
        ('Zara', 'B'),
        ('Kalmia', 'B'),
        # C Tier
        ('Lore', 'C'),
        ('Aimee', 'C'),
        ('Reiya', 'C'),
        # Untiered / Rogue
        ('Dungeon', 'Untiered'),
    ]
    
    # User Statistics & Match History
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, name TEXT, points INTEGER, 
                  wins INTEGER, losses INTEGER, streak INTEGER, history TEXT)''')
    
    # Leaderboard & Bot Configuration
    c.execute('''CREATE TABLE IF NOT EXISTS config 
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # RPG Profile Customization (class_name removed)
    c.execute('''CREATE TABLE IF NOT EXISTS profiles 
                 (user_id TEXT PRIMARY KEY, cashtag TEXT,
                  title TEXT DEFAULT 'Aspirant', 
                  signature_move TEXT DEFAULT 'None', 
                  embed_color TEXT)''')

    # 1. Official Meta Archetypes
    c.execute("""CREATE TABLE IF NOT EXISTS archetypes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        tier TEXT DEFAULT 'Untiered'
    )""")

    # 2. Match History with Deck Tracking
    c.execute("""CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        p1_id TEXT, 
        p2_id TEXT,
        p1_deck TEXT, 
        p2_deck TEXT,
        winner_id TEXT,
        status TEXT DEFAULT 'active',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    )""")
              
    
    # --- Lightweight migrations (safe on existing DBs) ---
    # Add 'notes' column to matches if it doesn't exist yet.
    c.execute("PRAGMA table_info(matches)")
    match_cols = {row[1] for row in c.fetchall()}
    if "notes" not in match_cols:
        try:
            c.execute("ALTER TABLE matches ADD COLUMN notes TEXT")
        except sqlite3.OperationalError:
            # If the column exists due to a race/deploy mismatch, ignore.
            pass

    c.executemany("INSERT OR IGNORE INTO archetypes (name, tier) VALUES (?, ?)", meta_decks)
    conn.commit()
    conn.close()
    print(f"🚀 Database initialized, Meta tracking active: {DB_NAME}")

    

    

# --- Rank Config ---
RANKS = [
    {"name": "DIAMOND", "emoji": "<:Diamond:1477427100666433572>", "min": 1800, "color": 0x00ffff},
    {"name": "PLATINUM", "emoji": "<:Platinum:1477426802317201411>", "min": 1600, "color": 0xe5e4e2},
    {"name": "GOLD", "emoji": "<:Gold:1477426026945577000>", "min": 1400, "color": 0xffd700},
    {"name": "SILVER", "emoji": "<:Silver:1477427675067842588>", "min": 1200, "color": 0xc0c0c0},
    {"name": "BRONZE", "emoji": "<:rookie:1476994147935322265>", "min": 0, "color": 0xcd7f32}
]


 #3.DATABASE HELPER (Block 1)
def get_or_create_user(user_id, name):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
        user = c.fetchone()

        if user is None:
            user = (str(user_id), name, 1000, 0, 0, 0, "")
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", user)
        else:
            # Keep display name current
            if user[1] != name:
                c.execute("UPDATE users SET name=? WHERE user_id=?", (name, str(user_id)))
                user = (user[0], name) + user[2:]

        conn.commit()
        return user
def update_user_stats(u_id, pts, wins, losses, streak, history):
    # Logic Fix: If history is somehow still a string, turn it into a list
    if isinstance(history, str):
        history = history.split(",") if history else []

    # Keep only the last 10 matches to prevent the DB cell from getting too huge
    hist_str = ",".join(history[-10:])

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET points=?, wins=?, losses=?, streak=?, history=? WHERE user_id=?",
            (pts, wins, losses, streak, hist_str, str(u_id)),
        )
        conn.commit()
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

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())


class LeaderboardWebView(discord.ui.View):
    def __init__(self, url):
        super().__init__(timeout=None) # Persistent button
        self.add_item(discord.ui.Button(
            label="View Full Rankings", 
            url=url, 
            style=discord.ButtonStyle.link,
            emoji="🌐"
        ))



class MatchReportingView(discord.ui.View):
    def __init__(self, p1, p2, match_id):
        # UI & Expiration fix: Buttons live for 2 hours to cover long games
        super().__init__(timeout=7200.0)
        self.p1, self.p2 = p1, p2
        self.match_id = match_id
        self.reports = {p1.id: None, p2.id: None}
        
        # Set specific labels from your original code
        self.report_p1.label = f"{p1.display_name} Won"
        self.report_p2.label = f"{p2.display_name} Won"
        
        self.forfeit_task = None  # The 30-minute fuse
        # Used for safe edits if an interaction expires (e.g., auto-forfeit).
        self.channel_id: int | None = None
        self.message_id: int | None = None

    async def start_forfeit_timer(self, interaction):
        """Waits 30 mins after the first report, then awards win to the reporter."""
        await asyncio.sleep(1800) 
        p1_rep, p2_rep = self.reports[self.p1.id], self.reports[self.p2.id]

        # If only one person reported, they are the winner by forfeit
        if (p1_rep and not p2_rep) or (p2_rep and not p1_rep):
            winner_id = p1_rep if p1_rep else p2_rep
            # We call your existing finalize logic to handle the Elo/Roles
            await self.finalize(interaction, winner_id, forfeit=True)

    async def finalize(self, interaction, winner_id, forfeit=False):
        """Your original Elo & Database logic, updated for Forfeits."""
        w_mem = self.p1 if winner_id == self.p1.id else self.p2
        l_mem = self.p2 if winner_id == self.p1.id else self.p1
        
        # 1. Update Match Table
        conn = get_conn()
        c = conn.cursor()
        notes = "Auto-Forfeit: No response" if forfeit else "Standard Match"
        c.execute("UPDATE matches SET winner_id = ?, status = 'completed', notes = ? WHERE id = ?", 
                  (str(winner_id), notes, self.match_id))
        conn.commit()
        conn.close()

        # 2. Points & History Logic (Directly from your original code)
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

        # 3. Success Embed
        rank_info = get_rank_info(r1 + pts)
        title = "⚠️ FORFEIT VERIFIED" if forfeit else "⚔️ MATCH VERIFIED"
        embed = discord.Embed(title=title, color=rank_info["color"])
        embed.description = f"**{w_mem.display_name}** defeated **{l_mem.display_name}**"
        if forfeit:
            embed.description += "\n*(Opponent failed to report within 30 minutes)*"
        
        embed.add_field(name="RESULTS", value=f"📈 **{w_mem.display_name}**: `+{pts} RP`\n📉 **{l_mem.display_name}**: `-{pts} RP`", inline=False)
        embed.set_footer(text="Arena Tracker • Meta Data Recorded")
        
        # If auto-forfeited, fetch the message by ID so we're not dependent on an expired interaction.
        if forfeit:
            try:
                channel = bot.get_channel(self.channel_id) if self.channel_id else None
                if channel is None and self.channel_id:
                    channel = await bot.fetch_channel(self.channel_id)
                if channel and self.message_id:
                    msg = await channel.fetch_message(self.message_id)
                    await msg.edit(content=None, embed=embed, view=None)
            except Exception as e:
                print(f"❌ Auto-forfeit message edit failed: {e}")
        else:
            await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="Player A Won", style=discord.ButtonStyle.success, emoji="⚔️", row=1)
    async def report_p1(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1.id, self.p2.id]: return
        self.reports[interaction.user.id] = self.p1.id
        await self.check_reports(interaction)

    @discord.ui.button(label="Player B Won", style=discord.ButtonStyle.success, emoji="⚔️", row=1)
    async def report_p2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1.id, self.p2.id]: return
        self.reports[interaction.user.id] = self.p2.id
        await self.check_reports(interaction)

    @discord.ui.button(label="Technical Issue / Dispute", style=discord.ButtonStyle.secondary, emoji="🛠️", row=2)
    async def pause_timer(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stops the 30m fuse and pings staff."""
        if interaction.user.id not in [self.p1.id, self.p2.id]: return
        
        if self.forfeit_task and self.forfeit_task != "PAUSED":
            self.forfeit_task.cancel()
            self.forfeit_task = "PAUSED"
            
        embed = discord.Embed(
            title="🛠️ MATCH FROZEN",
            description=f"**{interaction.user.display_name}** flagged an issue.\nAuto-forfeit disabled. <@&{MOD_ROLE_ID}> review required.",
            color=0x95a5a6
        )
        await interaction.response.edit_message(content=f"<@&{MOD_ROLE_ID}>", embed=embed, view=None)

    async def check_reports(self, interaction):
        p1_rep, p2_rep = self.reports[self.p1.id], self.reports[self.p2.id]
        
        if p1_rep and p2_rep:
            if self.forfeit_task and self.forfeit_task != "PAUSED":
                self.forfeit_task.cancel()
            
            if p1_rep != p2_rep:
                embed = discord.Embed(
                    title="⚠️ MATCH DISPUTE",
                    description=f"**{self.p1.display_name}** and **{self.p2.display_name}** reported differently.\nA <@&{MOD_ROLE_ID}> must resolve via `!settle`.",
                    color=0xe74c3c
                )
                await interaction.response.edit_message(content=f"<@&{MOD_ROLE_ID}>", embed=embed, view=None)
            else:
                await self.finalize(interaction, p1_rep)
        else:
            # First Report Trigger
            if not self.forfeit_task:
                other_player = self.p2 if interaction.user.id == self.p1.id else self.p1
                self.forfeit_task = asyncio.create_task(self.start_forfeit_timer(interaction))
                await interaction.response.edit_message(
                    content=f"⏳ **{interaction.user.display_name}** reported. <@{other_player.id}> has **30 mins** to confirm or face an auto-loss."
                )
            else:
                # Already waiting
                await interaction.response.edit_message(content=f"⏳ Still waiting for opponent to confirm...")
                
                


class DeckSelect(discord.ui.Select):
    def __init__(self, match_id, player_id, player_name):
        # Pulling the current meta list from your DB for the options
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT name FROM archetypes")
        decks = [row[0] for row in c.fetchall()]
        conn.close()

        options = [discord.SelectOption(label=d) for d in decks]
        super().__init__(
            placeholder=f"{player_name}, select your deck...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"select_{player_id}" # Unique ID for each player's dropdown
        )
        self.match_id = match_id
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction):
        # Security: Only the assigned player can use their specific dropdown
        if str(interaction.user.id) != str(self.player_id):
            return await interaction.response.send_message("This isn't your menu!", ephemeral=True)
        
        selected_deck = self.values[0]
        
        conn = get_conn()
        c = conn.cursor()
        
        # Determine if they are P1 or P2 in this match
        c.execute("SELECT p1_id FROM matches WHERE id = ?", (self.match_id,))
        p1_id = c.fetchone()[0]
        
        column = "p1_deck" if str(interaction.user.id) == p1_id else "p2_deck"
        
        # Save choice to DB
        c.execute(f"UPDATE matches SET {column} = ? WHERE id = ?", (selected_deck, self.match_id))
        conn.commit()
        
        # Check if BOTH players have selected now
        c.execute("SELECT p1_deck, p2_deck FROM matches WHERE id = ?", (self.match_id,))
        p1_d, p2_d = c.fetchone()
        conn.close()

        await interaction.response.send_message(f"✅ {interaction.user.display_name} locked in **{selected_deck}**!", ephemeral=False)

        # If both decks are in, authorize the match
        if p1_d and p2_d:
            await interaction.channel.send(f"⚔️ **MATCH AUTHORIZED** ⚔️\n**{p1_d}** vs **{p2_d}**\n*Go to your stations!*")
            # You can also trigger a message to clear the view here if you want

class MatchView(discord.ui.View):
    def __init__(self, match_id, p1, p2):
        super().__init__(timeout=None) # No timeout so the menu doesn't die
        self.add_item(DeckSelect(match_id, p1.id, p1.display_name))
        self.add_item(DeckSelect(match_id, p2.id, p2.display_name))




class OpenMatchView(discord.ui.View):
    def __init__(self, challenger):
        # 10 minute timeout for the lobby to stay active
        super().__init__(timeout=600)
        self.challenger = challenger
        self._claim_lock = asyncio.Lock()
        self.claimed = False
        self.guild_id = None
        self.channel_id = None
        self.message_id = None

    async def on_timeout(self):
        # If the lobby was claimed, the message has already been converted into the live match view.
        if self.claimed:
            return

        # Disable all components (button) to show the lobby expired
        for item in self.children:
            item.disabled = True

        # Try to edit the original lobby message to mark it expired
        if not self.channel_id or not self.message_id:
            return

        channel = bot.get_channel(self.channel_id)
        if channel is None:
            return

        try:
            msg = await channel.fetch_message(self.message_id)
        except Exception:
            return

        # Update footer to indicate expiry
        embed = msg.embeds[0] if msg.embeds else None
        if embed:
            embed.set_footer(text="This lobby has expired.")
        await msg.edit(embed=embed, view=self)

    @discord.ui.button(label="Join Match", style=discord.ButtonStyle.success, emoji="🎮")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Prevent the creator from joining their own match
        if interaction.user.id == self.challenger.id:
            return await interaction.response.send_message("You can't join your own lobby!", ephemeral=True)

        # Prevent multiple users from claiming the lobby (race condition)
        async with self._claim_lock:
            if self.claimed:
                return await interaction.response.send_message("This lobby has already been claimed.", ephemeral=True)
            self.claimed = True
            button.disabled = True

        opponent = interaction.user

        # Create match entry in SQLite using the existing DB helpers
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO matches (p1_id, p2_id, status) VALUES (?, ?, 'active')",
                (str(self.challenger.id), str(opponent.id))
            )
            match_id = c.lastrowid

        # Build the starting embed
        embed = discord.Embed(
            title="⚔️ MATCH STARTING",
            description=(
                "A challenger has appeared!\n\n"
                f"**Challenger:** {self.challenger.mention}\n"
                f"**Opponent:** {opponent.mention}"
            ),
            color=0x3498db
        )

        # Reuse existing MatchReportingView and DeckSelect
        view = MatchReportingView(self.challenger, opponent, match_id)
        view.add_item(DeckSelect(match_id, self.challenger.id, self.challenger.display_name))
        view.add_item(DeckSelect(match_id, opponent.id, opponent.display_name))

        # Capture message/channel IDs for safe edits (e.g., auto-forfeit after interaction expiry)
        view.channel_id = interaction.channel.id
        view.message_id = interaction.message.id

        # Edit the lobby message into the live match UI
        await interaction.response.edit_message(
            content=f"🔔 {self.challenger.mention}, your match against {opponent.mention} is starting!",
            embed=embed,
            view=view
        )

class ChallengeView(discord.ui.View):
    def __init__(self, p1, p2):
        super().__init__(timeout=300)
        self.p1, self.p2 = p1, p2

    @discord.ui.button(label="Accept Match", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.p2.id: return
        
        # 1. Create the Match Entry in the DB
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO matches (p1_id, p2_id, status) VALUES (?, ?, 'active')", 
                  (str(self.p1.id), str(self.p2.id)))
        match_id = c.lastrowid
        conn.commit()
        conn.close()

        # 2. Show the Deck Selection UI
        embed = discord.Embed(
            title="⚔️ MATCH ACTIVE",
            description=(f"Match started between **{self.p1.display_name}** and **{self.p2.display_name}**.\n\n"
                         "**Step 1:** Both players must select their deck below.\n"
                         "**Step 2:** Once finished, report the winner using the buttons."),
            color=0x3498db
        )
        
        # We combine the Deck Selection and Reporting into one view for efficiency
        view = MatchReportingView(self.p1, self.p2, match_id)
        # Add the dropdowns to the reporting view
        view.add_item(DeckSelect(match_id, self.p1.id, self.p1.display_name))
        view.add_item(DeckSelect(match_id, self.p2.id, self.p2.display_name))
        # Capture message/channel IDs for safe edits (e.g., auto-forfeit after interaction expiry)
        view.channel_id = interaction.channel.id
        view.message_id = interaction.message.id
        
        await interaction.response.edit_message(content=None, embed=embed, view=view)


        

# --- Commands ---

@bot.command(name="intro")
@commands.has_permissions(administrator=True)
async def intro(ctx):
    """Generates the official Arena Archive landing page."""
    
    # --- INTERNAL LOGIC (Keeps the command from crashing) ---
    MATCHMAKING_CHANNEL_ID = 1477881887601983669 
    LEADERBOARD_URL = "https://fezyinya-boop.github.io/Arena-Tracker/"
    
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM matches WHERE status = 'completed'")
        total_matches = c.fetchone()[0]
        conn.close()
    except Exception:
        total_matches = 0

    # --- THE EMBED (Your exact text/formatting) ---
    embed = discord.Embed(
        title="🏛️ WELCOME TO ARCHIVE ARENA",
        description=(
            "The definitive home for online Grand Archive play. Be a sweat and "
            "climb the tiers, or sling a rouge deck for fun, its up to you.\n\n"
            "This server is powered by a custom **Arena Tracker Agent** "
            "that monitors every match, calculates Elo (RP), and tracks the global meta. "
            "Automated Tournaments, Cash Prizes, and more."
        ),
        color=0x2b2d31 # Sleek Dark Grey
    )

    progression = (
        f"<:Diamond:1477427100666433572> **DIAMOND** — `1800+ RP`\n"
        f"<:Platinum:1477426802317201411> **PLATINUM** — `1600 RP`\n"
        f"<:Gold:1477426026945577000> **GOLD** — `1400 RP`\n"
        f"<:Silver:1477427675067842588> **SILVER** — `1200 RP`\n"
        f"<:rookie:1476994147935322265> **BRONZE** — `The Starting Line`"
    )
    embed.add_field(name="🏆 THE PATH TO CHAMPION", value=progression, inline=False)

    rules = (
        "⚖️ **Fair Play:** Respect your opponents. Salt belongs in the ocean, not the Arena.\n"
        "📊 **Elo System:** Beating high ranks gains more RP. Losing to lower ranks drops more RP.\n"
        "⚔️ **Meta Tracking:** Always select the correct archetype for accurate global stats."
    )
    embed.add_field(name="📜 ARENA GUIDELINES", value=rules, inline=False)

    matchmaking = (
        f"• Head over to <#{MATCHMAKING_CHANNEL_ID}>\n"
        "• Use `!challenge @user` to initiate a duel.\n"
        "• Select your decks and report results via the buttons provided."
    )
    embed.add_field(name="⚔️ MATCHMAKING 101", value=matchmaking, inline=False)

    embed.set_footer(text=f"Arena Agent v3.0 • {total_matches} matches recorded • Auto-Elo Enabled")

    # --- THE INTERACTIVE BUTTONS ---
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="View Global Rankings", 
        url=LEADERBOARD_URL, 
        style=discord.ButtonStyle.link,
        emoji="🌐"
    ))
    view.add_item(discord.ui.Button(
        label="Jump to Matchmaking", 
        url=f"https://discord.com/channels/{ctx.guild.id}/{MATCHMAKING_CHANNEL_ID}", 
        style=discord.ButtonStyle.link,
        emoji="🏹"
    ))

    await ctx.send(embed=embed, view=view)
    


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



@bot.command(name="decklist")
async def decklist(ctx, *, search: str = None):
    """Shows the meta directory or searches for a specific deck."""
    conn = get_conn()
    c = conn.cursor()

    # --- SEARCH LOGIC ---
    if search:
        # We use LIKE so "rai" matches "Rai"
        c.execute("SELECT name, tier FROM archetypes WHERE name LIKE ?", (f"%{search}%",))
        result = c.fetchone()
        conn.close()

        if result:
            name, tier = result
            embed = discord.Embed(title=f"🔍 Archetype Found: {name}", color=0x3498db)
            embed.add_field(name="Current Tier", value=f"**{tier}**")
            embed.set_footer(text="Use !meta to see win rates for this deck.")
            return await ctx.send(embed=embed)
        else:
            return await ctx.send(f"❌ No deck found matching `{search}`. Check your spelling or use `!decklist` for the full list.")

    # --- FULL LIST LOGIC ---
    c.execute("""
        SELECT name, tier FROM archetypes 
        ORDER BY CASE tier 
            WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END
    """)
    decks = c.fetchall()
    conn.close()

    if not decks:
        return await ctx.send("📭 The decklist is currently empty.")

    embed = discord.Embed(
        title="⚔️ ARENA ARCHIVE: DECKLIST",
        description="A list of all registered archetypes. Use `!decklist [name]` to search.",
        color=0x2f3136
    )

    # Grouping for the Embed
    tiers = {}
    for name, tier in decks:
        if tier not in tiers: tiers[tier] = []
        tiers[tier].append(name)

    tier_emojis = {"S": "⭐", "A": "🥇", "B": "🥈", "C": "🥉"}
    for tier, names in tiers.items():
        embed.add_field(name=f"{tier_emojis.get(tier, '🃏')} {tier}-Tier", value=" • ".join(names), inline=False)

    # Adding the interactive dropdown for the full list
    class DecklistSelect(discord.ui.Select):
        def __init__(self, options):
            super().__init__(placeholder="Select a deck for quick info...", options=options)
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_message(f"✅ Selected **{self.values[0]}**. Use `!meta` to see how it performs!", ephemeral=True)

    view = discord.ui.View()
    dropdown_options = [discord.SelectOption(label=d[0]) for d in decks[:25]]
    view.add_item(DecklistSelect(dropdown_options))

    await ctx.send(embed=embed, view=view)
    


@bot.command()
async def meta(ctx):
    """Shows a snapshot of recorded deck-vs-deck win rates."""
    query = """
    SELECT
        p1_deck AS deck_a,
        p2_deck AS deck_b,
        COUNT(*) AS games,
        SUM(CASE WHEN winner_id = p1_id THEN 1 ELSE 0 END) AS wins
    FROM matches
    WHERE p1_deck IS NOT NULL
      AND p2_deck IS NOT NULL
      AND status = 'completed'
    GROUP BY p1_deck, p2_deck
    ORDER BY games DESC, deck_a ASC, deck_b ASC
    """

    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(query)
            rows = c.fetchall()

        if not rows:
            return await ctx.send("📊 **No meta data yet.** Start settling some matches with decks locked in!")

        # Build table rows
        table_rows = []
        for deck_a, deck_b, games, wins in rows:
            games = int(games or 0)
            wins = int(wins or 0)
            wr = round((wins / games) * 100, 1) if games > 0 else 0.0
            table_rows.append([deck_a, deck_b, games, wins, wr])

        table = tabulate(
            table_rows,
            headers=["Deck A", "Deck B", "Games", "Wins", "WR%"],
            tablefmt="pretty",
            showindex=False
        )

        await ctx.send(f"📊 **CURRENT ARENA META SNAPSHOT**\n```\n{table}\n```")

    except Exception as e:
        print(f"Meta Command Error: {e}")
        await ctx.send("❌ Error calculating meta stats. Make sure matches are being settled properly.")
@bot.command()
async def leaderboard(ctx):
    # This just triggers the same refresh logic manually
    await refresh_leaderboard(ctx.guild)
    await ctx.send("✅ Leaderboard refreshed!")
    
    
    


@bot.event
async def on_ready():
    print(f"GUILD_ID: {GUILD_ID}, type: {type(GUILD_ID)}")
    cmds = bot.tree.get_commands()
    print(f"Commands in tree: {[c.name for c in cmds]}")
    init_db()
    start_keep_alive_once()

    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Final sync: {len(synced)} commands")
        else:
            await bot.tree.sync()
            print("🌍 Slash commands synced globally (may take time to appear)")
    except Exception as e:
        print(f"Sync error: {e}")

    print(f'Logged in as {bot.user.name}')



@bot.command()
@commands.has_permissions(administrator=True)
async def backup(ctx):
    """Sends a copy of the database file as a backup."""
    if os.path.exists(DB_NAME):
        try:
            # We use a copy to avoid "Database Locked" errors if the bot is writing to it
            file = discord.File(DB_NAME, filename="arena_backup.db")
            await ctx.send("📦 **Archive Arena Database Backup**\nKeep this file safe!", file=file)
        except Exception as e:
            await ctx.send(f"❌ Backup failed: `{e}`")
    else:
        await ctx.send("❌ Database file not found.")
        


        

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

    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO profiles (user_id) VALUES (?)", (str(ctx.author.id),))
    c.execute(f"UPDATE profiles SET {valid_fields[field]} = ? WHERE user_id = ?", (value, str(ctx.author.id)))
    conn.commit()
    conn.close()
    
    await ctx.send(f"✅ Your **{field}** has been updated to: `{value}`")




    
    




        

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



@bot.command(name="match")
async def match(ctx):
    """Starts an open lobby that anyone can join."""
    view = OpenMatchView(ctx.author)
    embed = discord.Embed(
        title="🏟️ OPEN LOBBY",
        description=(
            f"**{ctx.author.display_name}** is looking for an opponent!\n"
            "Click the button below to join the arena."
        ),
        color=0x2ecc71
    )
    embed.set_footer(text="This lobby will expire in 10 minutes.")
    msg = await ctx.send(embed=embed, view=view)
    # Cache IDs so on_timeout can disable the lobby cleanly
    view.guild_id = ctx.guild.id if ctx.guild else None
    view.channel_id = ctx.channel.id
    view.message_id = msg.id



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
        progress_val = f"{bar} {int((current_progress/total_needed)*100)}% to {next_rank['emoji']}"
    else:
        progress_val = "▰▰▰▰▰▰▰▰▰▰ **ASCENDED**"

    # --- Build the Embed ---
    embed = discord.Embed(title=f"{member.display_name}", color=r_info["color"])
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
    try:
        channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel: 
            print("⚠️ Leaderboard channel ID is incorrect or inaccessible.")
            return

        # 1. Fetch Top 10 from Database
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT name, points, streak FROM users ORDER BY points DESC LIMIT 10")
        top_players = c.fetchall()
        
        # 2. Get the saved message ID (to avoid spamming the channel)
        c.execute("SELECT value FROM config WHERE key = 'leaderboard_msg_id'")
        row = c.fetchone()
        saved_msg_id = int(row[0]) if row else None
        conn.close()

        # 3. Construct the Leaderboard Text
        embed = discord.Embed(
            title="⚔️ ARCHIVE ARENA: TOP 10", 
            color=0xFFD700,
            timestamp=discord.utils.utcnow() # Adds a "Last Updated" clock
        )
        
        description = ""
        for i, (name, pts, streak) in enumerate(top_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"
            fire = "🔥" if streak >= 3 else ""
            description += f"{medal} **{name}** {fire} — `{pts} RP`\n"
        
        embed.description = description or "The arena is currently empty..."
        embed.set_footer(text="Rankings refresh after every match")

        # 4. Initialize the Link Button View
        # Your GitHub Pages URL
        site_url = "https://fezyinya-boop.github.io/Arena-Tracker/"
        view = LeaderboardWebView(url=site_url)

        # 5. Update the Message
        msg = None
        if saved_msg_id:
            try:
                msg = await channel.fetch_message(saved_msg_id)
                await msg.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden):
                # If message was deleted or we lost perms, send a new one
                msg = await channel.send(embed=embed, view=view)
        else:
            msg = await channel.send(embed=embed, view=view)

        # 6. Save the Message ID if it changed
        if msg and (not saved_msg_id or msg.id != saved_msg_id):
            conn = get_conn()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('leaderboard_msg_id', ?)", (str(msg.id),))
            conn.commit()
            conn.close()

    except Exception as e:
        print(f"❌ Leaderboard Refresh Error: {e}")
        
        


@bot.command()
@commands.has_permissions(manage_messages=True)
async def settle(ctx, winner: discord.Member, loser: discord.Member):
    conn = get_conn()
    c = conn.cursor()

    # 1. DATABASE CLEANUP: Find and close any 'active' match between these two
    c.execute("""
        SELECT id, p1_deck, p2_deck FROM matches 
        WHERE ((p1_id = ? AND p2_id = ?) OR (p1_id = ? AND p2_id = ?))
        AND status = 'active'
        ORDER BY timestamp DESC LIMIT 1
    """, (str(winner.id), str(loser.id), str(loser.id), str(winner.id)))
    
    match_row = c.fetchone()

    if match_row:
        match_id, d1, d2 = match_row
        # Mark the match as completed and assign the winner for !meta stats
        c.execute("UPDATE matches SET winner_id = ?, status = 'completed' WHERE id = ?", 
                  (str(winner.id), match_id))
        conn.commit()
        meta_note = f"✅ Matchup **{d1} vs {d2}** recorded in meta stats."
    else:
        meta_note = "⚠️ No active match found in DB. RP adjusted manually (no meta data recorded)."

    # 2. RP CALCULATION (ELO Logic)
    w_data = get_or_create_user(winner.id, winner.display_name)
    l_data = get_or_create_user(loser.id, loser.display_name)
    
    r1, r2 = w_data[2], l_data[2]
    # Standard ELO formula: pts = K * (1 - expected_score)
    pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))
    
    # 3. UPDATE USER STATS
    w_hist = w_data[6].split(",") if w_data[6] else []
    l_hist = l_data[6].split(",") if l_data[6] else []
    
    w_hist.append(f"W:{loser.display_name}:{pts}")
    l_hist.append(f"L:{winner.display_name}:{pts}")

    # Winner: +Points, +Wins, +Streak
    update_user_stats(winner.id, r1 + pts, w_data[3] + 1, w_data[4], w_data[5] + 1, w_hist)
    # Loser: -Points, +Losses, Reset Streak
    update_user_stats(loser.id, r2 - pts, l_data[3], l_data[4] + 1, 0, l_hist)
    
    conn.close()

    # 4. DISCORD UPDATES (Roles & Leaderboard)
    await update_player_role(winner, r1 + pts)
    await update_player_role(loser, r2 - pts)
    await refresh_leaderboard(ctx.guild)
    
    # 5. VERDICT EMBED
    embed = discord.Embed(title="⚖️ JUDGE VERDICT", color=0xe74c3c)
    embed.description = f"**{winner.display_name}** has been awarded victory over **{loser.display_name}**."
    embed.add_field(name="RP SHIFT", value=f"📈 {winner.display_name}: `+{pts}`\n📉 {loser.display_name}: `-{pts}`")
    embed.set_footer(text=meta_note)
    
    await ctx.send(embed=embed)
    
    
    



# --- Tournament Globals ---
tournament_players = []  # List of member objects
tournament_active = False
tournament_bracket = []  # List of match dictionaries

@bot.command(name="payout_info", aliases=["payouts", "tourney"]) 
async def payout_info_launcher(ctx):
    """Displays tournament structure and the private registration process."""
    # Ensure you have MOD_ROLE_ID defined at the top of your script
    embed = discord.Embed(
        title="🏆 ARCHIVE ARENA: TOURNAMENT & PAYOUTS",
        description=(
            "Follow these steps to ensure you are eligible for prizes. "
            "Failure to comply results in an automatic DQ."
        ),
        color=0x00D632 # Cash App Green
    )

    embed.add_field(
        name="📝 HOW TO LINK YOUR CASH APP",
        value=(
            "To receive your prize, you must link your cashtag handle to our internal database:\n"
            "1. Type **`!register $YourTag`** (e.g., `!register $ArchiveKing`).\n"
            "2. **PRIVACY:** Your $Cashtag is **NOT** visible to others or on your profile card.\n"
            "3. **STAFF ACCESS:** Only authorized Mods view this for prize distribution.\n"
            "4. **CONTROL:** You can wipe your data at any time by typing **`!unregister`**."
        ),
        inline=False
    )

    embed.add_field(
        name="📲 PAYOUT POLICIES",
        value=(
            "• **Accuracy:** We are not responsible for typos. Double-check your tag!\n"
            "• **Claim Period:** You have 24 hours post-tourney to have a tag registered.\n"
            "• **Validation:** Matches must use `!duel`. No off-record games allowed."
        ),
        inline=False
    )

    embed.add_field(
        name="⚖️ DISPUTES",
        value=f"Screenshots or screen recordings are required of a finalized game state . A <@&{MOD_ROLE_ID}> will `!settle` any conflicts.",
        inline=False
    )

    embed.set_footer(text="Archive Arena • Payout System")
    await ctx.send(embed=embed)


@bot.command()
async def register(ctx, tag: str):
    """Links a user's Cashtag to their profile for payouts."""
    if not tag.startswith('$'):
        return await ctx.send("❌ **Error:** Your tag must start with `$` (e.g., `!register $ArchiveKing`)")

    conn = get_conn()
    c = conn.cursor()
    
    try:
        # This saves the 'tag' specifically into the 'cashtag' column we defined
        c.execute("""
            INSERT INTO profiles (user_id, cashtag) 
            VALUES (?, ?) 
            ON CONFLICT(user_id) DO UPDATE SET cashtag = excluded.cashtag
        """, (str(ctx.author.id), tag))
        
        conn.commit()
        
        embed = discord.Embed(
            title="✅ REGISTRATION SUCCESSFUL",
            description=f"Your payout handle has been set to **{tag}**.",
            color=0x00D632 # Cash App Green
        )
        embed.set_footer(text="This information is hidden from your public profile.")
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"⚠️ **Database Error:** {e}")
    finally:
        conn.close()


@bot.command()
async def payout(ctx, member: discord.Member):
    is_mod = any(role.id == MOD_ROLE_ID for role in ctx.author.roles)
    is_admin = ctx.author.guild_permissions.administrator
    if not (is_mod or is_admin):
        return await ctx.send("🚫 **Access Denied:** You need the Moderator role to use this.")

    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT cashtag FROM profiles WHERE user_id = ?", (str(member.id),))
        result = c.fetchone()
        if result and result[0]:
            await ctx.author.send(f"💸 **Payout Info for {member.display_name}:** `{result[0]}`")
            await ctx.send("✅ Payout info sent to your DMs.", delete_after=5)
        else:
            await ctx.send(f"❌ **{member.display_name}** has not registered a $Cashtag.")
    except Exception as e:
        await ctx.send(f"⚠️ **Database Error:** `{e}`")
    finally:
        conn.close()


    
    


@bot.command()
async def unregister(ctx):
    """Completely wipes the user's cashtag from the database."""
    conn = get_conn()
    c = conn.cursor()
    try:
        # 1. Execute the wipe
        c.execute("UPDATE profiles SET cashtag = NULL WHERE user_id = ?", (str(ctx.author.id),))
        
        # 2. Commit the change (The most important part!)
        conn.commit()
        
        # 3. Double check if it actually worked
        if c.rowcount > 0:
            await ctx.send("🗑️ **Data Cleared:** Your $Cashtag has been removed from our records.")
        else:
            await ctx.send("ℹ️ **Notice:** You didn't have a $Cashtag registered, or your profile doesn't exist yet.")
            
    except Exception as e:
        await ctx.send(f"⚠️ **Database Error:** `{e}`")
    finally:
        conn.close()

    

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
        conn = get_conn()
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
    embed.set_footer(text="Archive Arena")
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

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 100):
    """Deletes a specified number of messages (default 100)."""
    # This deletes the command message + the amount specified
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"✅ Cleared `{len(deleted)-1}` messages.", delete_after=5)


# --- 1. Flask App Initialization ---
app = Flask(__name__)
CORS(app)

# --- 2. The Health Check Route (Required by Railway) ---
@app.route('/')
def home():
    # This prevents the "Website Offline" error by giving Railway a success signal
    return "Arena Tracker API is Online"

@app.route('/api/leaderboard')
def get_leaderboard():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name, points, wins, losses, streak FROM users ORDER BY points DESC LIMIT 50")
    data = [{"name": r[0], "points": r[1], "wins": r[2], "losses": r[3], "streak": r[4]} for r in c.fetchall()]
    conn.close()
    return jsonify(data)

# --- 3. The Run Function with Dynamic Port ---
def run():
    # Railway assigns a random port; this line fetches it automatically
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- 4. The Keep Alive Thread ---
def keep_alive():
    t = Thread(target=run)
    t.daemon = True # This ensures the thread dies if the bot crashes
    t.start()


# Guard so we don't try to bind the Flask port twice (e.g. both __main__ and on_ready).
KEEP_ALIVE_STARTED = False

def start_keep_alive_once():
    global KEEP_ALIVE_STARTED
    if KEEP_ALIVE_STARTED:
        return
    KEEP_ALIVE_STARTED = True
    keep_alive()
# --- 5. Main Execution Block ---
if __name__ == "__main__":
    init_db()      # Initialize your SQLite tables
    start_keep_alive_once()   # Start the website thread

# --- Slash Command Wrappers ---
# These provide /match, /duel, etc. while keeping the existing !commands for backwards compatibility.

def _is_mod_or_admin(member: discord.Member) -> bool:
    try:
        is_admin = member.guild_permissions.administrator
    except Exception:
        is_admin = False
    is_mod = any(getattr(r, "id", None) == MOD_ROLE_ID for r in getattr(member, "roles", []))
    return is_admin or is_mod


@bot.tree.command(name="match", description="Start an open lobby that anyone can join.")
async def match_slash(interaction: discord.Interaction):

    duel_channel = bot.get_channel(DUEL_CHANNEL_ID)

    if duel_channel is None:
        return await interaction.response.send_message(
            "⚠️ Duel channel not found. Contact an admin.",
            ephemeral=True
        )

    view = OpenMatchView(interaction.user)

    embed = discord.Embed(
        title="⚔️ MATCH QUEUED",
        description=f"**{interaction.user.display_name}** is looking for an opponent!\nClick the button below to join the arena.",
        color=0x2ecc71
    )

    embed.set_footer(text="This lobby will expire in 10 minutes.")

    # Send confirmation to the user
    await interaction.response.send_message(
        f"⚔️ Lobby created in {duel_channel.mention}!",
        ephemeral=True
    )

    # Send the actual lobby to the duel channel
    msg = await duel_channel.send(embed=embed, view=view)

    # Store message references for timeout handling
    view.guild_id = interaction.guild.id
    view.channel_id = duel_channel.id
    view.message_id = msg.id

@bot.tree.command(name="duel", description="Challenge a specific player to a match.")
@app_commands.describe(opponent="The player you want to challenge")
async def duel_slash(interaction: discord.Interaction, opponent: discord.Member):
    if opponent == interaction.user:
        return await interaction.response.send_message("❌ You can't duel yourself!", ephemeral=True)
    if opponent.bot:
        return await interaction.response.send_message("❌ Bots can’t duel.", ephemeral=True)

    view = ChallengeView(interaction.user, opponent)
    embed = discord.Embed(
        title="⚔️ CHALLENGE ISSUED",
        description=f"{opponent.mention}, **{interaction.user.display_name}** has challenged you to a duel!\n\nDo you accept?",
        color=0x7289da
    )
    embed.set_footer(text="Arena Tracker • Awaiting Response")
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="rank", description="Show a player's rank, RP, record, and progress.")
@app_commands.describe(member="Leave blank to view your own rank")
async def rank_slash(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user

    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]
    r_info = get_rank_info(pts)

    next_rank = next((r for r in reversed(RANKS) if r['min'] > pts), None)
    if next_rank:
        total_needed = next_rank['min'] - r_info['min']
        current_progress = pts - r_info['min']
        percent = min(max(int((current_progress / total_needed) * 10), 0), 10)
        bar = "▰" * percent + "▱" * (10 - percent)
        progress_val = f"{bar} {int((current_progress/total_needed)*100)}% to {next_rank['emoji']}"
    else:
        progress_val = "▰▰▰▰▰▰▰▰▰▰ **ASCENDED**"

    total_games = data[3] + data[4]
    win_rate = round((data[3] / total_games) * 100) if total_games > 0 else 0

    embed = discord.Embed(title=f"{member.display_name}", color=r_info["color"])
    embed.add_field(name="🏆 RATING", value=f"{pts} RP", inline=True)
    embed.add_field(name="🔥 STREAK", value=f"{data[5]} Wins", inline=True)
    embed.add_field(name="⚔️ RECORD", value=f"{data[3]}W - {data[4]}L ({win_rate}%)", inline=False)
    embed.add_field(name="🚀 PROGRESS", value=progress_val, inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="history", description="Show your last 10 recorded matches.")
@app_commands.describe(member="Leave blank to view your own history")
async def history_slash(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    data = get_or_create_user(member.id, member.display_name)
    raw_hist = data[6].split(",") if data[6] else []

    if not raw_hist:
        return await interaction.response.send_message(f"No match history for {member.display_name}.", ephemeral=True)

    display = ""
    for entry in reversed(raw_hist):
        parts = entry.split(":")
        if len(parts) >= 3:
            res, opp, rp = parts[0], parts[1], parts[2]
            circle = "🟢" if res == "W" else "🔴"
            prefix = "+" if res == "W" else "-"
            display += f"{circle} **{res}** vs {opp} (`{prefix}{rp} RP`)\n"
        elif len(parts) == 1 and parts[0]:
            res = parts[0]
            circle = "🟢" if res == "W" else "🔴"
            display += f"{circle} **{res}** (Legacy Match)\n"

    embed = discord.Embed(title=f"📜 {member.display_name}'s History", description=display or "No recent matches recorded.", color=0x3498db)
    embed.set_footer(text="Last 10 Matches")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Refresh and show the top leaderboard message in the leaderboard channel.")
async def leaderboard_slash(interaction: discord.Interaction):
    await refresh_leaderboard(interaction.guild)
    await interaction.response.send_message("✅ Leaderboard refreshed!", ephemeral=True)


@bot.tree.command(name="meta", description="Show the current deck matchup meta snapshot.")
async def meta_slash(interaction: discord.Interaction):
    # Reuse the same logic as the prefix command (SQL aggregation + tabulate).
    conn = get_conn()
    query = """
    SELECT
        p1_deck AS deck_a,
        p2_deck AS deck_b,
        COUNT(*) AS games,
        SUM(CASE WHEN winner_id = p1_id THEN 1 ELSE 0 END) AS wins
    FROM matches
    WHERE p1_deck IS NOT NULL
      AND p2_deck IS NOT NULL
      AND status = 'completed'
    GROUP BY p1_deck, p2_deck
    ORDER BY games DESC, wins DESC
    """
    try:
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return await interaction.response.send_message("📊 **No meta data yet.** Start settling some matches with decks locked in!", ephemeral=True)

    # Build table rows with WR%
    table_rows = []
    for deck_a, deck_b, games, wins in rows:
        wr = round((wins / games) * 100, 1) if games else 0.0
        table_rows.append([deck_a, deck_b, games, wins, wr])

    table = tabulate(table_rows, headers=["Deck A", "Deck B", "Games", "Wins", "WR%"], tablefmt="pretty")
    await interaction.response.send_message(f"📊 **CURRENT ARENA META SNAPSHOT**\n```\n{table}\n```")


@bot.tree.command(name="decklist", description="Show the archetype directory or search for a deck.")
@app_commands.describe(search="Optional deck name to search for")
async def decklist_slash(interaction: discord.Interaction, search: str | None = None):
    conn = get_conn()
    c = conn.cursor()

    if search:
        c.execute("SELECT name, tier FROM archetypes WHERE name LIKE ?", (f"%{search}%",))
        result = c.fetchone()
        conn.close()
        if result:
            name, tier = result
            embed = discord.Embed(title=f"🔍 Archetype Found: {name}", color=0x3498db)
            embed.add_field(name="Current Tier", value=f"**{tier}**")
            embed.set_footer(text="Use /meta to see how it performs.")
            return await interaction.response.send_message(embed=embed)
        return await interaction.response.send_message(f"❌ No deck found matching `{search}`.", ephemeral=True)

    c.execute("""
        SELECT name, tier FROM archetypes
        ORDER BY CASE tier
            WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END
    """)
    decks = c.fetchall()
    conn.close()

    if not decks:
        return await interaction.response.send_message("📭 The decklist is currently empty.", ephemeral=True)

    embed = discord.Embed(
        title="⚔️ ARENA ARCHIVE: DECKLIST",
        description="A list of all registered archetypes. Use `/decklist search:<name>` to search.",
        color=0x2f3136
    )

    tiers = {}
    for name, tier in decks:
        tiers.setdefault(tier, []).append(name)

    tier_emojis = {"S": "⭐", "A": "🥇", "B": "🥈", "C": "🥉"}
    for tier, names in tiers.items():
        embed.add_field(name=f"{tier_emojis.get(tier, '🃏')} {tier}-Tier", value=" • ".join(names), inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rules", description="Show the official Archive Arena rules and ranking system.")
async def rules_slash(interaction: discord.Interaction):
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
            "victory and wait for a moderator to settle it.\n\n"
            "**3. Sportsmanship**\n"
            "Toxic behavior, stalling, or 'counter-picking' outside allowed parameters is prohibited."
        ),
        color=0x7289da
    )
    embed.add_field(name="📊 RANKING SYSTEM", value=rank_summary, inline=False)
    embed.set_footer(text="Play Fair, Duel Hard")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="register", description="Link your Cash App cashtag (private, for payouts).")
@app_commands.describe(tag="Your cashtag, e.g. $ArchiveKing")
async def register_slash(interaction: discord.Interaction, tag: str):
    if not tag.startswith('$'):
        return await interaction.response.send_message("❌ Your tag must start with `$` (e.g., `/register $ArchiveKing`).", ephemeral=True)

    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO profiles (user_id, cashtag)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET cashtag = excluded.cashtag
            """,
            (str(interaction.user.id), tag)
        )
        conn.commit()
    finally:
        conn.close()

    embed = discord.Embed(
        title="✅ REGISTRATION SUCCESSFUL",
        description=f"Your payout handle has been set to **{tag}**.",
        color=0x00D632
    )
    embed.set_footer(text="This information is hidden from your public profile.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="unregister", description="Remove your cashtag from the database.")
async def unregister_slash(interaction: discord.Interaction):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE profiles SET cashtag = NULL WHERE user_id = ?", (str(interaction.user.id),))
        conn.commit()
        changed = c.rowcount > 0
    finally:
        conn.close()

    if changed:
        await interaction.response.send_message("🗑️ **Data Cleared:** Your $Cashtag has been removed from our records.", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ You didn't have a $Cashtag registered.", ephemeral=True)


@bot.tree.command(name="payout_info", description="Show tournament payouts and how to link your cashtag.")
async def payout_info_slash(interaction: discord.Interaction):
    # Reuse the same embed content as the prefix command.
    embed = discord.Embed(
        title="🏆 ARCHIVE ARENA: TOURNAMENT & PAYOUTS",
        description=(
            "Follow these steps to ensure you are eligible for prizes. "
            "Failure to comply results in an automatic DQ."
        ),
        color=0x00D632
    )
    embed.add_field(
        name="📝 HOW TO LINK YOUR CASH APP",
        value=(
            "To receive your prize, you must link your cashtag handle to our internal database:\n"
            "1. Type **`/register $YourTag`** (e.g., `/register $ArchiveKing`).\n"
            "2. **PRIVACY:** Your $Cashtag is **NOT** visible to others or on your profile card.\n"
            "3. **STAFF ACCESS:** Only authorized Mods view this for prize distribution.\n"
            "4. **CONTROL:** You can wipe your data at any time by typing **`/unregister`**."
        ),
        inline=False
    )
    embed.add_field(
        name="📲 PAYOUT POLICIES",
        value=(
            "• **Accuracy:** We are not responsible for typos. Double-check your tag!\n"
            "• **Claim Period:** You have 24 hours post-tourney to have a tag registered.\n"
            "• **Validation:** Matches must use `/duel` or `/match`. No off-record games allowed."
        ),
        inline=False
    )
    embed.add_field(
        name="⚖️ DISPUTES",
        value=f"Screenshots or recordings are required. A <@&{MOD_ROLE_ID}> will resolve conflicts.",
        inline=False
    )
    embed.set_footer(text="Archive Arena • Payout System")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="payout", description="(Mods) Get a player's cashtag via DM.")
@app_commands.describe(member="Player to retrieve payout info for")
async def payout_slash(interaction: discord.Interaction, member: discord.Member):
    if not _is_mod_or_admin(interaction.user):
        return await interaction.response.send_message("🚫 Access denied.", ephemeral=True)

    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT cashtag FROM profiles WHERE user_id = ?", (str(member.id),))
        result = c.fetchone()
    finally:
        conn.close()

    if result and result[0]:
        try:
            await interaction.user.send(f"💸 **Payout Info for {member.display_name}:** `{result[0]}`")
            await interaction.response.send_message("✅ Payout info sent to your DMs.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I couldn't DM you (privacy settings).", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ **{member.display_name}** has not registered a $Cashtag.", ephemeral=True)


@bot.tree.command(name="settle", description="(Mods) Resolve a disputed match and award victory.")
@app_commands.describe(winner="Winner of the match", loser="Loser of the match")
async def settle_slash(interaction: discord.Interaction, winner: discord.Member, loser: discord.Member):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("🚫 You need Manage Messages to use this.", ephemeral=True)

    # Defer because settle does DB + leaderboard work
    await interaction.response.defer(ephemeral=True)

    # Reuse the same logic as the prefix settle command, adapted to interaction.
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        SELECT id, p1_deck, p2_deck FROM matches
        WHERE ((p1_id = ? AND p2_id = ?) OR (p1_id = ? AND p2_id = ?))
          AND status = 'active'
        ORDER BY timestamp DESC LIMIT 1
        """,
        (str(winner.id), str(loser.id), str(loser.id), str(winner.id))
    )
    match_row = c.fetchone()

    if match_row:
        match_id, d1, d2 = match_row
        c.execute("UPDATE matches SET winner_id = ?, status = 'completed' WHERE id = ?", (str(winner.id), match_id))
        conn.commit()
        meta_note = f"✅ Matchup **{d1} vs {d2}** recorded in meta stats."
    else:
        meta_note = "⚠️ No active match found in DB. RP adjusted manually (no meta data recorded)."

    w_data = get_or_create_user(winner.id, winner.display_name)
    l_data = get_or_create_user(loser.id, loser.display_name)
    r1, r2 = w_data[2], l_data[2]
    pts = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))

    w_hist = w_data[6].split(",") if w_data[6] else []
    l_hist = l_data[6].split(",") if l_data[6] else []

    w_hist.append(f"W:{loser.display_name}:{pts}")
    l_hist.append(f"L:{winner.display_name}:{pts}")

    update_user_stats(winner.id, r1 + pts, w_data[3] + 1, w_data[4], w_data[5] + 1, w_hist)
    update_user_stats(loser.id, r2 - pts, l_data[3], l_data[4] + 1, 0, l_hist)

    conn.close()

    await update_player_role(winner, r1 + pts)
    await update_player_role(loser, r2 - pts)
    await refresh_leaderboard(interaction.guild)

    embed = discord.Embed(title="⚖️ JUDGE VERDICT", color=0xe74c3c)
    embed.description = f"**{winner.display_name}** has been awarded victory over **{loser.display_name}**."
    embed.add_field(name="RP SHIFT", value=f"📈 {winner.display_name}: `+{pts}`\n📉 {loser.display_name}: `-{pts}`")
    embed.set_footer(text=meta_note)

    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="clear", description="(Mods) Delete a number of messages in this channel.")
@app_commands.describe(amount="How many messages to delete (default 100)")
async def clear_slash(interaction: discord.Interaction, amount: int = 100):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("🚫 You need Manage Messages to use this.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Cleared `{len(deleted)}` messages.", ephemeral=True)


# ---- GA card lookup (improved) ----
GATCG_API_BASE = "https://api.gatcg.com"

async def ga_autocomplete(session, partial: str):
    partial = (partial or "").strip()
    if not partial:
        return []
    url = f"{GATCG_API_BASE}/cards/autocomplete?name={urllib.parse.quote(partial)}"
    async with session.get(url, timeout=15) as r:
        if r.status != 200:
            return []
        return await r.json()  # expected: list of {name, slug, ...}

async def ga_get_by_slug(session, slug: str):
    slug = (slug or "").strip()
    if not slug:
        return None
    url = f"{GATCG_API_BASE}/cards/{urllib.parse.quote(slug)}"
    async with session.get(url, timeout=15) as r:
        if r.status != 200:
            return None
        return await r.json()



def ga_card_image_url(card: dict) -> str | None:
    # Try editions first
    editions = card.get("editions")
    if isinstance(editions, list) and editions:
        for ed in editions:
            if not isinstance(ed, dict):
                continue
            for key in ("image", "image_filename", "filename", "file"):
                v = ed.get(key)
                if isinstance(v, str) and v.strip():
                    return f"{GATCG_API_BASE}/cards/images/{v.strip()}"
            imgs = ed.get("images")
            if isinstance(imgs, dict):
                for k in ("large", "normal", "small", "png"):
                    v = imgs.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        return v

    # Try printings (common alternative)
    printings = card.get("printings")
    if isinstance(printings, list) and printings:
        for pr in printings:
            if not isinstance(pr, dict):
                continue
            for key in ("image", "image_filename", "filename", "file"):
                v = pr.get(key)
                if isinstance(v, str) and v.strip():
                    return f"{GATCG_API_BASE}/cards/images/{v.strip()}"
            imgs = pr.get("images")
            if isinstance(imgs, dict):
                for k in ("large", "normal", "small", "png"):
                    v = imgs.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        return v

    # Direct URL fallback (rare, but harmless)
    for k in ("image_url", "imageUrl", "art_url"):
        v = card.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v

    return None





def build_ga_embed(card: dict) -> discord.Embed:
    name = card.get("name", "Unknown Card")
    slug = card.get("slug", "")

    types = card.get("types") or card.get("type") or card.get("card_type")
    classes = card.get("classes") or []
    elements = card.get("elements") or []

    cost = None
    if isinstance(card.get("cost"), dict):
        cost = card.get("cost", {}).get("memory")
    else:
        cost = card.get("cost_memory") or card.get("memory_cost") or card.get("cost")

    text = card.get("effect") or card.get("effect_raw") or card.get("text") or card.get("rules_text") or ""

    e = discord.Embed(title=name, color=0x2b2d31)
    if slug:
        e.url = f"https://index.gatcg.com/cards/{slug}"

    if types:
        e.add_field(
            name="Type",
            value=", ".join(types) if isinstance(types, list) else str(types),
            inline=True,
        )
    if classes:
        e.add_field(name="Class", value=", ".join(classes), inline=True)
    if elements:
        e.add_field(name="Element", value=", ".join(elements), inline=True)
    if cost is not None:
        e.add_field(name="Cost", value=str(cost), inline=True)

    if text:
        if len(text) > 900:
            text = text[:900] + "…"
        e.add_field(name="Text", value=text, inline=False)

    img = ga_card_image_url(card)
    if img:
        e.set_image(url=img)

    return e

# ---- Discord autocomplete ----
async def card_name_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").strip()
    if len(current) < 2:
        return []

    async with aiohttp.ClientSession() as session:
        hits = await ga_autocomplete(session, current)

    choices = []
    for h in (hits or [])[:10]:
        nm = h.get("name")
        slug = h.get("slug")
        if nm and slug:
            choices.append(app_commands.Choice(name=nm, value=slug))
    return choices

# ---- /card command ----
@bot.tree.command(name="card", description="Look up a Grand Archive card (autocomplete).")
@app_commands.describe(card="Start typing a card name…")
@app_commands.autocomplete(card=card_name_autocomplete)
async def card_slash(interaction: discord.Interaction, card: str):
    """
    If user picks from autocomplete, `card` is a slug.
    If user types a raw name and hits enter, we fall back to autocomplete and pick top hit.
    """
    await interaction.response.defer(thinking=True)
    
async with aiohttp.ClientSession() as session:
    slug = (card or "").strip()

    full = await ga_get_by_slug(session, slug)

    if not full:
        hits = await ga_autocomplete(session, slug)
        if not hits:
            return await interaction.followup.send(f"❌ No card found for **{card}**.")

        slug2 = hits[0].get("slug")
        if not slug2:
            return await interaction.followup.send(f"❌ No card found for **{card}**.")

        full = await ga_get_by_slug(session, slug2)

    if not full:
        return await interaction.followup.send(f"❌ No card found for **{card}**.")

    # ---- DEBUG ----
    img = ga_card_image_url(full)

    print("SLUG:", full.get("slug"))
    print(
        "HAS EDITIONS:",
        isinstance(full.get("editions"), list),
        "LEN:",
        (len(full.get("editions")) if isinstance(full.get("editions"), list) else None),
    )

    print(
        "ED0 KEYS:",
        list(
            (full.get("editions")[0] if isinstance(full.get("editions"), list) and full.get("editions") else {}).keys()
        ),
    )

    print("IMG URL:", img)

    if img:
        async with session.get(img, timeout=10) as r:
            print("IMG STATUS:", r.status)
            print("IMG CONTENT-TYPE:", r.headers.get("Content-Type"))
            chunk = await r.content.read(32)
            print("IMG FIRST BYTES:", chunk)

    await interaction.followup.send(embed=build_ga_embed(full))
    




@bot.tree.command(name="profile", description="View a player's Archive Arena profile")
async def profile(interaction: discord.Interaction, member: discord.Member = None):

    member = member or interaction.user

    data = get_or_create_user(member.id, member.display_name)
    pts = data[2]

    conn = get_conn()
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

    try:
        avatar_img = await fetch_avatar(member.display_avatar.url)
    except:
        avatar_img = None

    try:
        await interaction.response.defer()

        buf = await asyncio.to_thread(
            make_profile_card,
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

        await interaction.followup.send(file=discord.File(buf, filename='profile.png'))

    except Exception as e:
        await interaction.followup.send(f"❌ Failed to generate profile card: `{e}`")

bot.run(TOKEN)
