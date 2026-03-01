from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os
import re

# --- FONT LOADER ---
def load_safe_font(size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans-Bold.ttf")
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    print("⚠️ Font not found, using default!")
    return ImageFont.load_default()

# --- BADGES ---
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

def make_profile_card(
    display_name, p_title, p_move, pts, wins, losses, streak, pct,
    current_rank_raw, next_rank_raw, rank_color, avatar_img=None
):
    # --- Rectangle card setup ---
    W, H = 700, 400
    card = Image.new('RGBA', (W, H), (0,0,0,255))  # solid black
    draw = ImageDraw.Draw(card)

    # --- Fonts ---
    f_name   = load_safe_font(36)
    f_rank   = load_safe_font(20)
    f_label  = load_safe_font(16)
    f_value  = load_safe_font(28)
    f_pts    = load_safe_font(60)
    f_prog   = load_safe_font(16)

    # --- Avatar ---
    av_size = 120
    av_x, av_y = 40, (H - av_size)//2
    if avatar_img:
        av = avatar_img.resize((av_size, av_size))
    else:
        av = Image.new('RGBA', (av_size,av_size), (50,50,50,255))

    # Circular mask
    mask = Image.new('L', (av_size,av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0,0),(av_size,av_size)], fill=255)
    av_circ = Image.new('RGBA', (av_size,av_size), (0,0,0,0))
    av_circ.paste(av, mask=mask)

    # Avatar ring
    ring_size = av_size + 10
    ring = Image.new('RGBA', (ring_size, ring_size), (0,0,0,0))
    ImageDraw.Draw(ring).ellipse([(0,0),(ring_size-1,ring_size-1)], outline=(*rank_color,255), width=5)
    card.paste(ring, (av_x-5, av_y-5), ring)
    card.paste(av_circ, (av_x,av_y), av_circ)

    # Current rank badge
    cur_badge = get_rank_badge(current_rank_raw, size=45)
    if cur_badge:
        card.paste(cur_badge, (av_x + av_size - 35, av_y + av_size - 35), cur_badge)

    # --- Header Text ---
    clean_cur = clean_rank_name(current_rank_raw)
    draw.text((av_x + av_size + 20, av_y + 20), display_name, font=f_name, fill=(255,255,255))
    draw.text((av_x + av_size + 20, av_y + 70), f"{clean_cur} · {p_title}", font=f_rank, fill=(*rank_color,255))

    # --- Stats block ---
    stats_x = av_x + av_size + 20
    stats_y = av_y + 110
    total_games = wins + losses
    wr = round((wins / total_games) * 100) if total_games>0 else 0

    draw.text((stats_x, stats_y), "RATING", font=f_label, fill=(180,180,180))
    draw.text((stats_x, stats_y+20), str(pts), font=f_pts, fill=(*rank_color,255))

    draw.text((stats_x+220, stats_y), "RECORD", font=f_label, fill=(180,180,180))
    draw.text((stats_x+220, stats_y+20), f"{wins}W {losses}L ({wr}%)", font=f_value, fill=(255,255,255))

    streak_label = "🔥 STREAK" if streak>=3 else "STREAK"
    draw.text((stats_x+220, stats_y+60), streak_label, font=f_label, fill=(180,180,180))
    draw.text((stats_x+220, stats_y+80), f"{streak} Win Streak", font=f_value, fill=(255,255,255))

    # Signature move
    draw.text((stats_x, stats_y+120), "SIGNATURE MOVE", font=f_label, fill=(180,180,180))
    draw.text((stats_x, stats_y+145), p_move, font=f_value, fill=(255,255,255))

    # --- Progress bar ---
    bar_x, bar_y = stats_x, stats_y + 200
    bar_w, bar_h = 300, 18
    draw.rounded_rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], radius=9, fill=(50,50,50))
    fill_w = int(bar_w * min(pct,1.0))
    if fill_w>5:
        draw.rounded_rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], radius=9, fill=(*rank_color,255))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=45)
        if next_badge:
            card.paste(next_badge, (bar_x+bar_w+10, bar_y-12), next_badge)
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((bar_x, bar_y-16), f"{int(pct*100)}% to {clean_next}", font=f_prog, fill=(200,200,200))

    # --- Save to buffer ---
    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
