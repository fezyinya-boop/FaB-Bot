from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os
import re

# --- FONTS ---
def load_custom_font(font_filename, size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
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
    rc = rank_color
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # --- BACKGROUND: subtle horizontal gradient ---
    for x in range(W):
        shade = int(14 * (1 - x / W))
        draw.line([(x, 0), (x, H)], fill=(shade, shade, shade, 255))

    # Radial glow behind avatar
    for r in range(280, 0, -8):
        a = int(20 * (1 - r / 280) ** 2)
        draw.ellipse([(50 - r, H//2 - r), (50 + r, H//2 + r)], fill=(*rc, a))

    # --- DIAGONAL SHEEN ---
    sheen = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sheen_draw = ImageDraw.Draw(sheen)
    for i in range(80):
        alpha = int(18 * (1 - abs(i - 40) / 40))
        sheen_draw.line([(i * 6 - H, 0), (i * 6, H)], fill=(255, 255, 255, alpha), width=3)
    card = Image.alpha_composite(card, sheen)
    draw = ImageDraw.Draw(card)

    # Thin top/bottom edge lines only (no left bar)
    draw.line([(0, 0), (W, 0)], fill=(*rc, 60), width=1)
    draw.line([(0, H-1), (W, H-1)], fill=(*rc, 60), width=1)

    # --- FONTS ---
    f_name  = load_custom_font("Orbitron-VariableFont_wght.ttf", 44)
    f_pts   = load_custom_font("Michroma-Regular.ttf", 68)
    # Headers: DejaVuSans-Bold for actual bold weight
    f_label = load_custom_font("DejaVuSans-Bold.ttf", 18)
    f_title = load_custom_font("Orbitron-VariableFont_wght.ttf", 22)
    f_value = load_custom_font("FunnelSans-Regular.ttf", 22)
    f_prog  = load_custom_font("FunnelSans-Light.ttf", 13)
    f_move  = load_custom_font("FunnelSans-Regular.ttf", 26)

    LABEL = (85, 85, 95)
    WHITE = (235, 232, 228)
    DIM   = (35, 35, 40)

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

    # Layered glow ring
    for gi in range(14, 0, -2):
        ga = int(50 * (1 - gi / 14) ** 1.5)
        draw.ellipse(
            [(av_x - gi, av_y - gi), (av_x + av_size + gi, av_y + av_size + gi)],
            outline=(*rc, ga), width=2
        )
    draw.ellipse(
        [(av_x - 5, av_y - 5), (av_x + av_size + 5, av_y + av_size + 5)],
        outline=(*rc, 200), width=4
    )
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Rank badge overlapping avatar corner — no background
    badge_size = 72
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        bx = av_x + av_size - 50
        by = av_y + av_size - 50
        card.paste(cur_badge, (bx, by), cur_badge)

    # --- COLUMNS ---
    col_name  = 295
    col_stats = 660

    # --- NAME ---
    draw.text((col_name, 38), display_name.upper(), font=f_name, fill=WHITE)
    try:
        name_w = draw.textlength(display_name.upper(), font=f_name)
    except:
        name_w = len(display_name) * 26
    draw.line([(col_name, 90), (col_name + int(name_w), 90)], fill=(*rc, 140), width=2)

    # --- RANK · TITLE ---
    clean_cur = clean_rank_name(current_rank_raw)
    draw.text((col_name, 100), clean_cur, font=f_title, fill=(*rc, 255))
    try:
        rank_w = draw.textlength(clean_cur, font=f_title)
    except:
        rank_w = len(clean_cur) * 14
    draw.text((col_name + rank_w + 10, 104), "·", font=f_value, fill=LABEL)
    draw.text((col_name + rank_w + 26, 100), p_title, font=f_title, fill=WHITE)

    # --- DIVIDER ---
    draw.line([(col_name, 140), (W - 30, 140)], fill=DIM, width=1)

    # --- RATING ---
    draw.text((col_name, 150), "RATING", font=f_label, fill=LABEL)
    draw.text((col_name, 174), str(pts), font=f_pts, fill=(*rc, 255))

    # --- RECORD ---
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0
    draw.text((col_stats, 150), "RECORD", font=f_label, fill=LABEL)
    draw.text((col_stats, 174), f"{wins}W – {losses}L", font=f_value, fill=WHITE)
    draw.text((col_stats, 204), f"{wr}% win rate", font=f_prog, fill=LABEL)

    # --- STREAK ---
    streak_col = (*rc, 255) if streak >= 3 else WHITE
    draw.text((col_stats, 252), "STREAK", font=f_label, fill=LABEL)
    streak_label = f"{streak} Wins  🔥" if streak >= 3 else f"{streak} Wins"
    draw.text((col_stats, 276), streak_label, font=f_value, fill=streak_col)

    # --- DIVIDER ---
    draw.line([(col_name, 325), (W - 30, 325)], fill=DIM, width=1)

    # --- SIGNATURE MOVE ---
    draw.text((col_name, 334), "SIGNATURE MOVE", font=f_label, fill=LABEL)
    draw.text((col_name, 358), p_move.upper(), font=f_move, fill=WHITE)

    # --- PROGRESS BAR ---
    bar_x = col_name
    bar_y = 422
    badge_slot = 52
    bar_w = W - col_name - 30 - badge_slot - 10
    bar_h = 8

    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((bar_x, bar_y - 18), f"{int(pct*100)}% to {clean_next}",
                  font=f_prog, fill=LABEL)
    else:
        draw.text((bar_x, bar_y - 18), "MAX RANK REACHED",
                  font=f_prog, fill=(*rc, 255))

    draw.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], fill=(30, 30, 35))
    fill_w = int(bar_w * min(pct, 1.0))
    if fill_w > 0:
        draw.rectangle([(bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h)], fill=(*rc, 255))

    gx = bar_x + fill_w
    for gi in range(10, 0, -1):
        ga = int(50 * (gi / 10) ** 2)
        draw.ellipse([(gx - gi, bar_y - gi//2), (gx + gi, bar_y + bar_h + gi//2)],
                     fill=(*rc, ga))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - 4)
        if next_badge:
            card.paste(next_badge,
                       (bar_x + bar_w + 12, bar_y + bar_h // 2 - (badge_slot - 4) // 2),
                       next_badge)

    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
                  
