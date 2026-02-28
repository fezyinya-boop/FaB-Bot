import discord
from discord.ext import commands
import os
import sqlite3
from datetime import datetime

# --- Environment ---
LEADERBOARD_CHANNEL_ID = int(os.environ['LEADERBOARD_CHANNEL_ID'])
LEADERBOARD_MSG_ID = 1476843531191717972  # Replace with your actual Message ID
MOD_ROLE_NAME = "Moderator"  # Must match your Discord role name exactly

# --- Database Setup ---
def get_db():
    conn = sqlite3.connect('arena.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                uid         TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                points      INTEGER DEFAULT 1000,
                wins        INTEGER DEFAULT 0,
                losses      INTEGER DEFAULT 0,
                streak      INTEGER DEFAULT 0,
                active_deck TEXT DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS match_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                winner_id   TEXT NOT NULL,
                loser_id    TEXT NOT NULL,
                winner_name TEXT NOT NULL,
                loser_name  TEXT NOT NULL,
                winner_deck TEXT,
                loser_deck  TEXT,
                rp_change   INTEGER NOT NULL,
                played_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS disputes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id        INTEGER NOT NULL,
                disputer_id     TEXT NOT NULL,
                disputer_name   TEXT NOT NULL,
                status          TEXT DEFAULT 'pending',
                resolved_by     TEXT DEFAULT NULL,
                resolved_at     TEXT DEFAULT NULL,
                FOREIGN KEY (match_id) REFERENCES match_history(id)
            );
        """)

init_db()

# --- DB Helpers ---
def get_player(uid: str, name: str = None):
    """Fetch player, creating them with defaults if they don't exist."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM players WHERE uid = ?", (uid,)).fetchone()
        if not row and name:
            conn.execute(
                "INSERT INTO players (uid, name) VALUES (?, ?)", (uid, name)
            )
            row = conn.execute("SELECT * FROM players WHERE uid = ?", (uid,)).fetchone()
        return dict(row) if row else None

def update_player(uid: str, **kwargs):
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [uid]
    with get_db() as conn:
        conn.execute(f"UPDATE players SET {fields} WHERE uid = ?", values)

def log_match(winner_id, loser_id, winner_name, loser_name, winner_deck, loser_deck, rp_change):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO match_history
               (winner_id, loser_id, winner_name, loser_name, winner_deck, loser_deck, rp_change, played_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (winner_id, loser_id, winner_name, loser_name, winner_deck, loser_deck, rp_change,
             datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
        )
        return cursor.lastrowid

def open_dispute(match_id, disputer_id, disputer_name):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO disputes (match_id, disputer_id, disputer_name) VALUES (?, ?, ?)",
            (match_id, disputer_id, disputer_name)
        )

def get_dispute(dispute_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        return dict(row) if row else None

def get_match(match_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM match_history WHERE id = ?", (match_id,)).fetchone()
        return dict(row) if row else None

def resolve_dispute(dispute_id, resolved_by):
    with get_db() as conn:
        conn.execute(
            "UPDATE disputes SET status = 'resolved', resolved_by = ?, resolved_at = ? WHERE id = ?",
            (resolved_by, datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), dispute_id)
        )

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- RANK CONFIG ---
RANKS = [
    {"name": "💎 DIAMOND",  "min": 1800, "color": 0x00ffff},
    {"name": "📀 PLATINUM", "min": 1600, "color": 0xe5e4e2},
    {"name": "🟡 GOLD",     "min": 1400, "color": 0xffd700},
    {"name": "🟣 SILVER",   "min": 1200, "color": 0xc0c0c0},
    {"name": "🟤 BRONZE",   "min": 0,    "color": 0xcd7f32}
]

def get_rank_info(points):
    for rank in RANKS:
        if points >= rank["min"]:
            return rank
    return RANKS[-1]

# --- Shared Helpers ---
async def update_live_leaderboard(guild):
    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel:
        return

    with get_db() as conn:
        top_10 = conn.execute(
            "SELECT * FROM players ORDER BY points DESC LIMIT 10"
        ).fetchall()

    embed = discord.Embed(title="🏆 ARCHIVE ARENA TOP 10", color=0xd4af37)
    description = ""
    for i, row in enumerate(top_10, 1):
        rank_info = get_rank_info(row['points'])
        streak = f"🔥{row['streak']}" if row['streak'] >= 3 else ""
        description += f"{i}. {rank_info['name']} **{row['name']}** - `{row['points']} RP` {streak}\n"

    embed.description = description or "No players yet."
    embed.set_footer(text="Updates automatically after every match.")

    try:
        msg = await channel.fetch_message(LEADERBOARD_MSG_ID)
        await msg.edit(embed=embed)
    except Exception as e:
        print(f"[Leaderboard] Could not edit message: {e}")
        await channel.send(embed=embed)

async def update_player_role(member, points):
    rank_info = get_rank_info(points)
    role = discord.utils.get(member.guild.roles, name=rank_info['name'])
    if role and role not in member.roles:
        all_rank_names = [r['name'] for r in RANKS]
        roles_to_remove = [r for r in member.roles if r.name in all_rank_names]
        await member.remove_roles(*roles_to_remove)
        await member.add_roles(role)

def is_moderator(member):
    return any(r.name == MOD_ROLE_NAME for r in member.roles)



# -----------------------------------------------------------------------
# STAGE 2: Both players vote on who won (30 min timer)
# -----------------------------------------------------------------------
class ResultView(discord.ui.View):
    """
    After the opponent accepts, both players see two buttons:
      "⚔️ {reporter} Won"  and  "⚔️ {opponent} Won"
    Both vote on the same winner — no ego barrier, no "I Lost" button.

    Outcomes:
      - Both agree        → match confirmed instantly
      - They disagree     → auto-dispute, mods pinged
      - Someone times out → the non-voter auto-forfeits
    """

    def __init__(self, reporter, opponent):
        super().__init__(timeout=None)  # Timer starts only after first vote
        self.reporter      = reporter
        self.opponent      = opponent
        self.message       = None
        self.votes         = {}  # uid -> member (who they voted as winner)
        self.timer_started = False

        # Label buttons with real display names
        self.reporter_btn.label = f"⚔️ {reporter.display_name} Won"
        self.opponent_btn.label = f"⚔️ {opponent.display_name} Won"

    async def on_timeout(self):
        missing = [
            p for p in (self.reporter, self.opponent)
            if str(p.id) not in self.votes
        ]
        if not missing:
            return  # Both voted, already resolved

        # Auto-forfeit: whoever didn't vote loses
        forfeiter = missing[0]
        winner    = self.opponent if forfeiter.id == self.reporter.id else self.reporter

        embed = await self._process_match(winner, forfeiter)
        forfeit_embed = discord.Embed(
            title="⏰ Auto-Forfeit",
            description=(
                f"**{forfeiter.display_name}** did not submit a result within 30 minutes "
                f"and has been auto-forfeited.\n\n" + embed.description
            ),
            color=embed.color
        )
        self.stop()
        if self.message:
            await self.message.edit(embed=forfeit_embed, view=None)

    @discord.ui.button(style=discord.ButtonStyle.primary)
    async def reporter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._record_vote(interaction, self.reporter)

    @discord.ui.button(style=discord.ButtonStyle.primary)
    async def opponent_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._record_vote(interaction, self.opponent)

    async def _record_vote(self, interaction: discord.Interaction, voted_winner):
        uid     = str(interaction.user.id)
        allowed = {str(self.reporter.id), str(self.opponent.id)}

        if uid not in allowed:
            return await interaction.response.send_message(
                "❌ You're not part of this match.", ephemeral=True
            )
        if uid in self.votes:
            return await interaction.response.send_message(
                "✅ You've already submitted your vote.", ephemeral=True
            )

        self.votes[uid] = voted_winner

        # Start the 30-min timer on the first vote
        if not self.timer_started:
            self.timer_started = True
            self.timeout = 1800
            self._refresh_timeout()

        await interaction.response.send_message(
            f"✅ Voted: **{voted_winner.display_name}** won. Waiting for the other player...",
            ephemeral=True
        )

        if len(self.votes) == 2:
            await self._resolve()

    async def _resolve(self):
        r_vote = self.votes.get(str(self.reporter.id))
        o_vote = self.votes.get(str(self.opponent.id))

        if r_vote.id == o_vote.id:
            # Agreement — process the match
            winner = r_vote
            loser  = self.opponent if winner.id == self.reporter.id else self.reporter
            embed  = await self._process_match(winner, loser)
            self.stop()
            await self.message.edit(embed=embed, view=None)
        else:
            # Disagreement — ping mods
            mod_role = discord.utils.get(self.reporter.guild.roles, name=MOD_ROLE_NAME)
            mention  = mod_role.mention if mod_role else "@Moderator"
            embed = discord.Embed(
                title="⚠️ Conflicting Results — Mod Review Required",
                description=(
                    f"**{self.reporter.display_name}** and **{self.opponent.display_name}** "
                    f"submitted conflicting results.\n"
                    f"**{self.reporter.display_name}** voted: {r_vote.display_name} won\n"
                    f"**{self.opponent.display_name}** voted: {o_vote.display_name} won\n\n"
                    f"A moderator must determine the outcome."
                ),
                color=0xffa500
            )
            self.stop()
            await self.message.edit(
                content=f"{mention} — conflicting match results need review.",
                embed=embed, view=None
            )

    async def _process_match(self, winner, loser):
        w_id, l_id = str(winner.id), str(loser.id)

        winner_data = get_player(w_id, winner.display_name)
        loser_data  = get_player(l_id, loser.display_name)
        old_rank    = get_rank_info(winner_data["points"])

        r1, r2 = winner_data["points"], loser_data["points"]
        pts    = round(32 * (1 - (1 / (1 + 10 ** ((r2 - r1) / 400)))))

        new_winner_points = winner_data["points"] + pts
        new_loser_points  = max(0, loser_data["points"] - pts)
        new_streak        = winner_data["streak"] + 1

        update_player(w_id, name=winner.display_name, points=new_winner_points,
                      wins=winner_data["wins"] + 1, streak=new_streak)
        update_player(l_id, name=loser.display_name, points=new_loser_points,
                      losses=loser_data["losses"] + 1, streak=0)

        match_id = log_match(
            w_id, l_id, winner.display_name, loser.display_name,
            winner_data.get("active_deck"), loser_data.get("active_deck"), pts
        )

        await update_player_role(winner, new_winner_points)
        await update_player_role(loser, new_loser_points)
        await update_live_leaderboard(winner.guild)

        new_rank    = get_rank_info(new_winner_points)
        rank_up_msg = (
            f"\n🆙 **RANK UP:** {winner.mention} ascended to **{new_rank['name']}**!"
            if new_rank["name"] != old_rank["name"] else ""
        )
        streak_msg      = f"\n🔥 **On a {new_streak} win streak!**" if new_streak >= 3 else ""
        winner_deck_str = f" *(playing {winner_data['active_deck']})*" if winner_data.get("active_deck") else ""
        loser_deck_str  = f" *(playing {loser_data['active_deck']})*"  if loser_data.get("active_deck")  else ""

        embed = discord.Embed(title="⚔️ MATCH VERIFIED", color=new_rank["color"])
        embed.description = (
            f"**{winner.display_name}**{winner_deck_str} defeated "
            f"**{loser.display_name}**{loser_deck_str}\n"
            f"`+{pts} RP` / `-{pts} RP`{streak_msg}{rank_up_msg}\n\n"
            f"*Match ID: #{match_id} — Use `!dispute {match_id}` to contest.*"
        )
        return embed


# -----------------------------------------------------------------------
# STAGE 1: Accept/Reject the match challenge (5 min)
# -----------------------------------------------------------------------
class ReportView(discord.ui.View):
    """Initial prompt sent to the opponent."""

    def __init__(self, reporter, opponent):
        super().__init__(timeout=300)  # 5 min to accept/reject
        self.reporter = reporter
        self.opponent = opponent
        self.message  = None

    async def on_timeout(self):
        embed = discord.Embed(
            title="⌛ Match Request Expired",
            description=(
                f"**{self.opponent.display_name}** did not respond to the match request. "
                f"No result recorded."
            ),
            color=0x888888
        )
        self.stop()
        if self.message:
            await self.message.edit(embed=embed, view=None)

    @discord.ui.button(label="Accept Match", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            return await interaction.response.send_message(
                "❌ Only the challenged player can accept.", ephemeral=True
            )
        self.stop()

        result_view = ResultView(self.reporter, self.opponent)
        embed = discord.Embed(
            title="⚔️ Match Accepted — Who Won?",
            description=(
                f"{self.reporter.mention} vs {self.opponent.mention}\n\n"
                f"Both players: click the button for whoever **won** the match.\n"
                f"If you both agree → confirmed instantly.\n"
                f"If you disagree → mods are notified.\n"
                f"No response in 30 minutes → auto-forfeit."
            ),
            color=0x00d4ff
        )
        await interaction.response.edit_message(embed=embed, view=result_view)
        result_view.message = await interaction.original_response()

    @discord.ui.button(label="Reject Match", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            return await interaction.response.send_message(
                "❌ Only the challenged player can reject.", ephemeral=True
            )
        self.stop()
        embed = discord.Embed(
            title="❌ Match Rejected",
            description=f"**{self.opponent.display_name}** declined the match. No result recorded.",
            color=0xed4245
        )
        await interaction.response.edit_message(embed=embed, view=None)


# -----------------------------------------------------------------------
# DISPUTE RESOLUTION VIEW  (shown in mod channel / thread)
# -----------------------------------------------------------------------
class DisputeView(discord.ui.View):
    def __init__(self, dispute_id, match_id, original_channel):
        super().__init__(timeout=None)  # Mods can take their time
        self.dispute_id = dispute_id
        self.match_id   = match_id
        self.original_channel = original_channel

    @discord.ui.button(label="Uphold Result", style=discord.ButtonStyle.success, emoji="✅")
    async def uphold(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_moderator(interaction.user):
            return await interaction.response.send_message("❌ Only Moderators can resolve disputes.", ephemeral=True)

        resolve_dispute(self.dispute_id, interaction.user.display_name)

        embed = discord.Embed(
            title="✅ Dispute Resolved — Result Upheld",
            description=f"Resolved by **{interaction.user.display_name}**. Original result stands.",
            color=0x57f287
        )
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)
        await self.original_channel.send(
            embed=discord.Embed(
                title="📋 Dispute Closed",
                description=f"Match **#{self.match_id}** dispute was reviewed. **Original result upheld.**",
                color=0x57f287
            )
        )

    @discord.ui.button(label="Overturn Result", style=discord.ButtonStyle.danger, emoji="🔄")
    async def overturn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_moderator(interaction.user):
            return await interaction.response.send_message("❌ Only Moderators can resolve disputes.", ephemeral=True)

        match = get_match(self.match_id)
        if not match:
            return await interaction.response.send_message("❌ Match not found.", ephemeral=True)

        # Reverse the RP changes
        rp = match['rp_change']
        winner_data = get_player(match['winner_id'])
        loser_data  = get_player(match['loser_id'])

        if winner_data:
            update_player(match['winner_id'],
                points=max(0, winner_data['points'] - rp),
                wins=max(0, winner_data['wins'] - 1),
                streak=max(0, winner_data['streak'] - 1)
            )
        if loser_data:
            update_player(match['loser_id'],
                points=loser_data['points'] + rp,
                losses=max(0, loser_data['losses'] - 1)
            )

        resolve_dispute(self.dispute_id, interaction.user.display_name)

        embed = discord.Embed(
            title="🔄 Dispute Resolved — Result Overturned",
            description=f"Resolved by **{interaction.user.display_name}**. RP changes have been reversed.",
            color=0xed4245
        )
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)
        await self.original_channel.send(
            embed=discord.Embed(
                title="📋 Dispute Closed",
                description=f"Match **#{self.match_id}** dispute was reviewed. **Result overturned — RP reversed.**",
                color=0xed4245
            )
        )


# -----------------------------------------------------------------------
# COMMANDS
# -----------------------------------------------------------------------

@bot.command()
async def report(ctx, opponent: discord.Member):
    """Report a match win. Opponent must confirm."""
    if opponent == ctx.author:
        return await ctx.send("❌ You can't fight yourself, Champion.")

    view = ReportView(ctx.author, opponent)
    e
