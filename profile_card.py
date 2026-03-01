from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import math
import re
import os
import discord

# ── Bulletproof Font Loading ──
def load_safe_font(size):
    """Railway-proof font loader. Tries Linux paths, then local, then default."""
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

# ── Rank badge image paths (Matches your 'rank_' prefix) ──
BADGES_DIR = os.path.join(os.path.dirname(__file__), 'badges')
RANK_BADGES = {
    "DIAMOND":  os.path.join(BADGES_DIR, 'rank_diamond.png'),
    "PLATINUM": os.path.join(BADGES_DIR, 'rank_platinum.png'),
    "GOLD":     os.path.join(BADGES_DIR, 'rank_gold.png'),
    "SILVER":   os.path.join(BADGES_DIR, 'rank_silver.png'),
    "BRONZE":   os.path.join(BADGES_DIR, 'rank_bronze.png'),
}

def clean_rank_name(name: str) -> str:
    """Strip Discord custom emoji tags."""
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

def get_rank_badge(rank_name_raw: str, size: int = 40) -> Image.Image | None:
    """Safety check for badge images to prevent bot crashes."""
    clean = clean_rank_name(rank_name_raw).upper()
    path = RANK_BADGES.get(clean)
    if not path or not os.path.exists(path):
        return None 
    try:
        return Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    except:
        return None

async def fetch_avatar(url: str) -> Image.Image | None:
    """Fetch avatar with timeout protection."""
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
    
    # --- 1. NEW "BIG MODE" DIMENSIONS ---
    W, H = 600, 500 
    card = Image.new('RGBA', (W, H), (30, 31, 36, 255))

    # Dot grid texture
    dots = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for y in range(20, H, 30):
        for x in range(20, W, 30):
            dd.ellipse([(x-1, y-1), (x+1, y+1)], fill=(255, 255, 255, 10))
    card = Image.alpha_composite(card, dots)

    draw = ImageDraw.Draw(card)

    # --- 2. UPSCALED FONTS ---
    f_name   = load_safe_font(42)  
    f_rank   = load_safe_font(18)  
    f_label  = load_safe_font(16)  
    f_value  = load_safe_font(22)  
    f_pts    = load_safe_font(65)  
    f_prog   = load_safe_font(16)  
    f_footer = load_safe_font(14)  

    # --- 3. LARGE AVATAR & RING ---
    av_size = 130 
    av_x, av_y = 40, 40
    if avatar_img:
        av = avatar_img.resize((av_size, av_size))
    else:
        av = Image.new('RGBA', (av_size, av_size), (55, 57, 63, 255))

    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size-1, av_size-1)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Thick Rank-Colored Ring
    ring_size = av_size + 8
    ring = Image.new('RGBA', (ring_size, ring_size), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        [(0, 0), (ring_size-1, ring_size-1)], outline=(*rank_color, 255), width=4)
    card.paste(ring, (av_x-4, av_y-4), ring)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Rank Badge (on Avatar)
    cur_badge = get_rank_badge(current_rank_raw, size=40)
    if cur_badge:
        card.paste(cur_badge, (av_x + av_size - 30, av_y + av_size - 30), cur_badge)

    # --- 4. HEADER TEXT ---
    name_x = av_x + av_size + 25
    name_y = av_y + 15
    clean_cur = clean_rank_name(current_rank_raw)
    draw.text((name_x, name_y), display_name, font=f_name, fill=(240, 240, 240, 255))
    draw.text((name_x, name_y + 55), f"{clean_cur} · {p_title}",
              font=f_rank, fill=(*rank_color, 210))

    # --- 5. STATS SECTION (REPOSITIONED) ---
    col1_x, row_y = 40, 210
    
    # Large Rating
    draw.text((col1_x, row_y), "RATING", font=f_label, fill=(130, 133, 142, 255))
    pts_str = str(pts)
    draw.text((col1_x, row_y+20), pts_str, font=f_pts, fill=(*rank_color, 255))

    # Record & Win Rate
    col2_x = 320
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0
    draw.text((col2_x, row_y), "RECORD", font=f_label, fill=(130, 133, 142, 255))
    draw.text((col2_x, row_y+20), f"{wins}W {losses}L ({wr}%)", font=f_value, fill=(220, 220, 220, 255))
    
    # Streak
    draw.text((col2_x, row_y+65), "STREAK", font=f_label, fill=(130, 133, 142, 255))
    draw.text((col2_x, row_y+85), f"{streak} Win Streak", font=f_value, fill=(220, 220, 220, 255))

    # Signature Move
    draw.text((col1_x, row_y + 110), "SIGNATURE MOVE", font=f_label, fill=(130, 133, 142, 255))
    draw.text((col1_x, row_y + 130), p_move, font=f_value, fill=(220, 220, 220, 255))

    # --- 6. CHONKY PROGRESS BAR ---
    bar_y, bar_x = H - 100, 40
    bar_w, bar_h = W - 140, 15
    draw.rounded_rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], radius=7, fill=(48, 50, 57, 255))
    
    fill_w = int(bar_w * min(pct, 1.0))
    if fill_w > 0:
        draw.rounded_rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], radius=7, fill=(*rank_color, 255))

    # Next Rank Text
    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((bar_x, bar_y + 25), f"{int(pct*100)}% to {clean_next}", font=f_prog, fill=(150, 153, 162, 255))
        
        # Next Badge
        next_badge = get_rank_badge(next_rank_raw, size=50)
        if next_badge:
            card.paste(next_badge, (bar_x + bar_w + 15, bar_y - 18), next_badge)

    # Footer
    draw.text((W // 2, H - 30), "Archive Arena · Season 1", font=f_footer, fill=(75, 77, 86, 255), anchor="mm")

    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
