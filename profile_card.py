from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import re
import os

# --- FONT LOADER ---
def load_safe_font(size):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "arial.ttf"
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

# --- BADGE PATHS ---
BADGES_DIR = os.path.join(os.path.dirname(__file__), 'badges')
RANK_BADGES = {
    "DIAMOND":  os.path.join(BADGES_DIR, 'rank_diamond.png'),
    "PLATINUM": os.path.join(BADGES_DIR, 'rank_platinum.png'),
    "GOLD":     os.path.join(BADGES_DIR, 'rank_gold.png'),
    "SILVER":   os.path.join(BADGES_DIR, 'rank_silver.png'),
    "BRONZE":   os.path.join(BADGES_DIR, 'rank_bronze.png'),
}

def clean_rank_name(name: str) -> str:
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

def get_rank_badge(rank_name_raw: str, size: int = 40):
    clean = clean_rank_name(rank_name_raw).upper()
    path = RANK_BADGES.get(clean)
    if not path or not os.path.exists(path):
        return None 
    try:
        return Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    except:
        return None

# --- AVATAR FETCH ---
async def fetch_avatar(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url), timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert('RGBA')
    except:
        pass
    return None

# --- PROFILE CARD GENERATOR ---
def make_profile_card(
    display_name: str,
    p_title: str,
    p_move: str,
    pts: int,
    wins: int,
    losses: int,
    streak: int,
    pct: float,
    current_rank_raw: str,
    next_rank_raw: str | None,
    rank_color: tuple,
    avatar_img: Image.Image | None = None,
) -> io.BytesIO:

    print("NEW PROFILE CARD VERSION LOADED")  # Debug line

    # --- CARD BASE ---
    W, H = 600, 600
    card = Image.new('RGBA', (W, H), (18, 18, 18, 255))  # dark background
    draw = ImageDraw.Draw(card)

    # --- FONTS ---
    f_name   = load_safe_font(80)
    f_rank   = load_safe_font(36)
    f_label  = load_safe_font(28)
    f_value  = load_safe_font(48)
    f_pts    = load_safe_font(130)
    f_prog   = load_safe_font(18)

    # --- AVATAR ---
    av_size = 180
    av_x = (W - av_size) // 2
    av_y = 50
    if avatar_img:
        av = avatar_img.resize((av_size, av_size))
    else:
        av = Image.new('RGBA', (av_size, av_size), (40, 40, 40, 255))

    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0,0),(av_size-1,av_size-1)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0,0,0,0))
    av_circ.paste(av, mask=mask)

    # Glow ring
    ring_size = av_size + 14
    ring = Image.new('RGBA', (ring_size, ring_size), (0,0,0,0))
    ImageDraw.Draw(ring).ellipse(
        [(0,0),(ring_size-1, ring_size-1)],
        outline=(*rank_color,255), width=7
    )
    card.paste(ring, (av_x-7, av_y-7), ring)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # --- CURRENT RANK BADGE ---
    cur_badge = get_rank_badge(current_rank_raw, size=55)
    if cur_badge:
        card.paste(cur_badge, (av_x + av_size - 40, av_y + av_size - 40), cur_badge)

    # --- HEADER TEXT ---
    draw.text((W//2, av_y + av_size + 35), display_name, font=f_name, fill=(255,255,255), anchor="mm")
    draw.text((W//2, av_y + av_size + 80), f"{clean_rank_name(current_rank_raw)} · {p_title}", font=f_rank, fill=(*rank_color,255), anchor="mm")

    # --- STATS GRID ---
    # Left: Rating
    draw.text((60, 330), "RATING", font=f_label, fill=(150,150,150))
    draw.text((60, 355), str(pts), font=f_pts, fill=(*rank_color,255))

    # Right: Record & Streak
    total = wins + losses
    wr = round((wins/total)*100) if total>0 else 0
    draw.text((340, 345), "RECORD", font=f_label, fill=(150,150,150))
    draw.text((340, 370), f"{wins}W {losses}L ({wr}%)", font=f_value, fill=(255,255,255))
    streak_label = "🔥 STREAK" if streak >=3 else "STREAK"
    draw.text((340, 415), streak_label, font=f_label, fill=(150,150,150))
    draw.text((340, 440), f"{streak} Win Streak", font=f_value, fill=(255,255,255))

    # Signature Move
    draw.text((60, 460), "SIGNATURE MOVE", font=f_label, fill=(150,150,150))
    draw.text((60, 485), p_move, font=f_value, fill=(255,255,255))

    # --- PROGRESS BAR ---
    bar_x, bar_y = 60, 535
    bar_w, bar_h = 420, 20
    draw.rounded_rectangle([(bar_x, bar_y),(bar_x+bar_w, bar_y+bar_h)], radius=10, fill=(40,40,40))
    fill_w = int(bar_w * min(pct,1.0))
    if fill_w>5:
        draw.rounded_rectangle([(bar_x, bar_y),(bar_x+fill_w, bar_y+bar_h)], radius=10, fill=(*rank_color,255))

    # Next rank badge & text
    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=60)
        if next_badge:
            card.paste(next_badge, (bar_x + bar_w + 15, bar_y - 20), next_badge)
        draw.text((bar_x, bar_y - 25), f"{int(pct*100)}% to {clean_rank_name(next_rank_raw)}", font=f_prog, fill=(180,180,180))

    # --- SAVE TO BUFFER ---
    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
