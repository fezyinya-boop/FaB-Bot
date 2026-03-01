import aiohttp
import io
import os
import re

# --- FONTS ---
def load_custom_font(font_filename, size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    # Fallback system fonts if custom fonts not found
    for path in [
        '/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-bold.otf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- FETCH AVATAR ---
async def fetch_avatar(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url), timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert('RGBA')
    except Exception as e:
        print(f"Avatar fetch error: {e}")
    return None

# --- RANK UTILS ---
def clean_rank_name(name: str) -> str:
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

BADGES_DIR = os.path.join(os.path.dirname(__file__), 'badges')
RANK_BADGES = {
    "DIAMOND":  os.path.join(BADGES_DIR, 'rank_diamond.png'),
    "PLATINUM": os.path.join(BADGES_DIR, 'rank_platinum.png'),
    "GOLD":     os.path.join(BADGES_DIR, 'rank_gold.png'),
    "SILVER":   os.path.join(BADGES_DIR, 'rank_silver.png'),
    "BRONZE":   os.path.join(BADGES_DIR, 'rank_bronze.png'),
}

def get_rank_badge(rank_name_raw: str, size: int = 60):
    clean = clean_rank_name(rank_name_raw).upper()
    path = RANK_BADGES.get(clean)
    if not path or not os.path.exists(path):
        return None
    try:
        return Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    except:
        return None

# --- CORE CARD GENERATOR ---
def make_profile_card(
    display_name, p_title, p_move, pts, wins, losses, streak, pct,
    current_rank_raw, next_rank_raw, rank_color, avatar_img=None
):
    W, H = 900, 460
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # Subtle background gradient
    for x in range(W):
        shade = int(12 * (1 - x / W))
        draw.line([(x, 0), (x, H)], fill=(shade, shade, shade, 255))

    # --- FONTS (your three custom fonts) ---
    f_name  = load_custom_font("Orbitron-VariableFont_wght.ttf", 44)
    f_pts   = load_custom_font("Michroma-Regular.ttf", 68)
    f_label = load_custom_font("Michroma-Regular.ttf", 13)
    f_title = load_custom_font("PirataOne-Regular.ttf", 34)
    f_value = load_custom_font("FunnelSans-Regular.ttf", 24)
    f_prog  = load_custom_font("FunnelSans-Light.ttf", 15)

    # --- AVATAR ---
    av_size = 220
    av_x = 40
    av_y = (H - av_size) // 2 - 20

    if not avatar_img:
        avatar_img = Image.new('RGBA', (av_size, av_size), (25, 25, 25, 255))

    av = avatar_img.resize((av_size, av_size))
    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size, av_size)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Rank-colored glow ring
    draw.ellipse(
        [(av_x-8, av_y-8), (av_x+av_size+8, av_y+av_size+8)],
        outline=(*rank_color, 255), width=8
    )
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Current rank badge on avatar corner
    badge_size = 72
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        bx = av_x + av_size - 60
        by = av_y + av_size - 60
        draw.ellipse([(bx-5, by-5), (bx+badge_size+5, by+badge_size+5)], fill=(0, 0, 0, 255))
        card.paste(cur_badge, (bx, by), cur_badge)

    # --- COLUMNS ---
    col_name  = 295   # Left text column
    col_stats = 660   # Right stats column (pushed far enough right to avoid RP overlap)

    # --- NAME + RANK · TITLE ---
    draw.text((col_name, 42), display_name.upper(), font=f_name, fill=(255, 255, 255))
    clean_cur = clean_rank_name(current_rank_raw)
    draw.text((col_name, 96), f"{clean_cur}  ·  {p_title}", font=f_title, fill=(*rank_color, 255))

    # Thin divider
    draw.line([(col_name, 148), (W - 30, 148)], fill=(40, 40, 40, 255), width=1)

    # --- RATING ---
    draw.text((col_name, 160), "RATING", font=f_label, fill=(110, 110, 110))
    draw.text((col_name, 178), str(pts), font=f_pts, fill=(*rank_color, 255))
    # "RP" label offset based on digit count
    rp_x = col_name + len(str(pts)) * 38 + 4
    draw.text((rp_x, 230), "RP", font=f_label, fill=(110, 110, 110))

    # --- RECORD ---
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0
    draw.text((col_stats, 160), "RECORD", font=f_label, fill=(110, 110, 110))
    draw.text((col_stats, 180), f"{wins}W - {losses}L", font=f_value, fill=(255, 255, 255))
    draw.text((col_stats, 212), f"{wr}% win rate", font=f_label, fill=(110, 110, 110))

    # --- STREAK ---
    streak_col = (255, 165, 30) if streak >= 3 else (255, 255, 255)
    draw.text((col_stats, 258), "STREAK", font=f_label, fill=(110, 110, 110))
    streak_label = f"{streak} Wins  🔥" if streak >= 3 else f"{streak} Wins"
    draw.text((col_stats, 278), streak_label, font=f_value, fill=streak_col)

    # Thin divider
    draw.line([(col_name, 335), (W - 30, 335)], fill=(40, 40, 40, 255), width=1)

    # --- SIGNATURE MOVE ---
    draw.text((col_name, 345), "SIGNATURE MOVE", font=f_label, fill=(110, 110, 110))
    draw.text((col_name, 365), p_move.upper(), font=f_value, fill=(255, 255, 255))

    # --- PROGRESS BAR ---
    bar_x = col_name
    bar_y = 418
    badge_slot = 52
    bar_w = W - col_name - 30 - badge_slot - 10
    bar_h = 10

    # Track
    draw.rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], fill=(38, 38, 38))
    # Fill
    fill_w = int(bar_w * min(pct, 1.0))
    if fill_w > 0:
        draw.rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], fill=(*rank_color, 255))

    # Glow tip
    gx = bar_x + fill_w
    for gi in range(10, 0, -1):
        ga = int(50 * (gi / 10) ** 2)
        draw.ellipse([(gx-gi, bar_y-gi//2), (gx+gi, bar_y+bar_h+gi//2)], fill=(*rank_color, ga))

    # Progress label + next rank badge
    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((bar_x, bar_y - 18), f"{int(pct*100)}% to {clean_next}",
                  font=f_prog, fill=(160, 160, 160))
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - 4)
        if next_badge:
            card.paste(next_badge, (bar_x + bar_w + 12, bar_y + bar_h // 2 - (badge_slot - 4) // 2), next_badge)
    else:
        draw.text((bar_x, bar_y - 18), "MAX RANK REACHED",
                  font=f_prog, fill=(*rank_color, 255))

    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
