from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os
import re

# --- FONT LOADER ---
def load_custom_font(font_filename, size):
    """Loads specific fonts from your /fonts folder with fallback."""
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    # Print warning to console if font is missing
    print(f"⚠️ Font {font_filename} not found at {font_path}")
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
    # --- 1. SQUARE SETUP ---
    W, H = 600, 600
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255)) # Solid Black Background
    draw = ImageDraw.Draw(card)

    # --- 2. THE TRIPLE-FONT SETUP ---
    # PIRATA ONE: Gothic Display for Player Name
    f_name = load_custom_font("PirataOne-Regular.ttf", 95) 
    
    # MICHROMA: Tech/Sci-fi for Headers and Rating
    f_pts   = load_custom_font("Michroma-Regular.ttf", 85)
    f_label = load_custom_font("Michroma-Regular.ttf", 16)
    
    # FUNNEL SANS: Modern/Clean for Stats and Titles
    f_rank  = load_custom_font("FunnelSans-Medium.ttf", 22)
    f_value = load_custom_font("FunnelSans-Regular.ttf", 28)
    f_prog  = load_custom_font("FunnelSans-Light.ttf", 18)

    # --- 3. JUMBO AVATAR ---
    av_size = 210
    av_x, av_y = (W - av_size) // 2, 45
    
    if avatar_img:
        av = avatar_img.resize((av_size, av_size))
    else:
        av = Image.new('RGBA', (av_size, av_size), (35, 35, 35, 255))

    # Masking
    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size, av_size)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Rank-Colored Ring
    draw.ellipse([(av_x-9, av_y-9), (av_x+av_size+9, av_y+av_size+9)], outline=(*rank_color, 255), width=10)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Rank Badge (on Avatar)
    cur_badge = get_rank_badge(current_rank_raw, size=65)
    if cur_badge:
        card.paste(cur_badge, (av_x + av_size - 48, av_y + av_size - 48), cur_badge)

    # --- 4. CENTERED HEADERS ---
    # Name in Pirata One
    draw.text((W//2, av_y + av_size + 45), display_name, font=f_name, fill=(255, 255, 255), anchor="mm")
    
    # Title in Funnel Sans (Capitalized and accented for style)
    clean_cur = clean_rank_name(current_rank_raw)
    draw.text((W//2, av_y + av_size + 100), f"{clean_cur.upper()}  //  {p_title.upper()}", font=f_rank, fill=(*rank_color, 255), anchor="mm")

    # --- 5. STATS GRID ---
    col1_x, col2_x = 55, 335
    row_y = 350

    # Rating (Michroma)
    draw.text((col1_x, row_y), "RATING", font=f_label, fill=(120, 120, 120))
    draw.text((col1_x, row_y + 20), str(pts), font=f_pts, fill=(*rank_color, 255))

    # Record (Header: Michroma | Value: Funnel Sans)
    draw.text((col2_x, row_y + 20), "BATTLE RECORD", font=f_label, fill=(120, 120, 120))
    draw.text((col2_x, row_y + 45), f"{wins}W - {losses}L", font=f_value, fill=(255, 255, 255))

    # Streak
    streak_label = "🔥 STREAK" if streak >= 3 else "STREAK"
    draw.text((col2_x, row_y + 95), streak_label, font=f_label, fill=(120, 120, 120))
    draw.text((col2_x, row_y + 120), f"{streak} Wins", font=f_value, fill=(255, 255, 255))

    # Signature Move
    draw.text((col1_x, row_y + 135), "SIGNATURE MOVE", font=f_label, fill=(120, 120, 120))
    draw.text((col1_x, row_y + 160), p_move, font=f_value, fill=(255, 255, 255))

    # --- 6. PROGRESS BAR (Flat Modern Style) ---
    bar_x, bar_y = 55, 550
    bar_w, bar_h = 430, 14
    draw.rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], fill=(40, 40, 40))
    
    fill_w = int(bar_w * min(pct, 1.0))
    if fill_w > 0:
        draw.rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], fill=(*rank_color, 255))

    # Next Rank Indicator
    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=70)
        if next_badge:
            card.paste(next_badge, (bar_x + bar_w + 10, bar_y - 25), next_badge)
        draw.text((bar_x, bar_y - 25), f"{int(pct*100)}% TO NEXT RANK", font=f_prog, fill=(180, 180, 180))

    # --- 7. SAVE TO BUFFER ---
    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
