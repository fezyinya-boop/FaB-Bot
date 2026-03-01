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
    return ImageFont.load_default()

# --- UTILS (Explicitly keeping fetch_avatar for main.py) ---
async def fetch_avatar(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url), timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert('RGBA')
    except Exception as e:
        print(f"Avatar fetch error: {e}")
    return None

def clean_rank_name(name: str) -> str:
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

# --- BADGE LOGIC ---
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

# --- CORE GENERATOR ---
def make_profile_card(
    display_name, p_title, p_move, pts, wins, losses, streak, pct,
    current_rank_raw, next_rank_raw, rank_color, avatar_img=None
):
    # 1. CANVAS (Clean Rectangle)
    W, H = 850, 450
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # 2. FONT SIZING (Orbitron Name)
    f_name  = load_custom_font("Orbitron-VariableFont_wght.ttf", 55)
    f_pts   = load_custom_font("Michroma-Regular.ttf", 90)
    f_label = load_custom_font("Michroma-Regular.ttf", 15)
    f_title = load_custom_font("PirataOne-Regular.ttf", 40) 
    f_value = load_custom_font("FunnelSans-Regular.ttf", 28)
    f_prog  = load_custom_font("FunnelSans-Light.ttf", 16)

    # 3. AVATAR & STATUS BADGE
    av_size = 220
    av_x, av_y = 50, (H - av_size) // 2 - 20
    
    if not avatar_img:
        avatar_img = Image.new('RGBA', (av_size, av_size), (30, 30, 30, 255))
    
    av = avatar_img.resize((av_size, av_size))
    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size, av_size)], fill=255)
    
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Outer Glow Ring
    draw.ellipse([(av_x-10, av_y-10), (av_x+av_size+10, av_y+av_size+10)], outline=(*rank_color, 255), width=10)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Status-Style Rank Badge (Discord Style)
    badge_size = 80
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        # Positioned bottom-right of PFP
        bx, by = av_x + av_size - 65, av_y + av_size - 65
        # Black "border" circle to separate badge from PFP
        draw.ellipse([(bx-5, by-5), (bx+badge_size+5, by+badge_size+5)], fill=(0,0,0,255))
        card.paste(cur_badge, (bx, by), cur_badge)

    # 4. DATA PLACEMENT (Widened to fix overlapping in 20511.png)
    col_x = 330
    col_stats = 600

    # Identity
    draw.text((col_x, 50), display_name.upper(), font=f_name, fill=(255, 255, 255))
    draw.text((col_x, 115), p_title, font=f_title, fill=(*rank_color, 255))

    # Rating (Michroma)
    draw.text((col_x, 200), "RATING", font=f_label, fill=(120, 120, 120))
    draw.text((col_x, 220), str(pts), font=f_pts, fill=(*rank_color, 255))

    # Stats (Funnel Sans)
    draw.text((col_stats, 205), "RECORD", font=f_label, fill=(120, 120, 120))
    draw.text((col_stats, 235), f"{wins}W - {losses}L", font=f_value, fill=(255, 255, 255))

    draw.text((col_stats, 285), "STREAK", font=f_label, fill=(120, 120, 120))
    draw.text((col_stats, 315), f"{streak} Wins", font=f_value, fill=(255, 255, 255))

    # Signature Move
    draw.text((col_x, 320), "SIGNATURE MOVE", font=f_label, fill=(120, 120, 120))
    draw.text((col_x, 345), p_move.upper(), font=f_value, fill=(255, 255, 255))

    # 5. BOTTOM PROGRESS BAR
    bar_x, bar_y = col_x, 410
    bar_w, bar_h = 470, 12
    draw.rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], fill=(40, 40, 40))
    fill_w = int(bar_w * min(pct, 1.0))
    draw.rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], fill=(*rank_color, 255))
    
    draw.text((bar_x, bar_y - 20), f"{int(pct*100)}% TO NEXT RANK", font=f_prog, fill=(180, 180, 180))

    # Save
    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
