from PIL import Image, ImageDraw, ImageFont
import io
import os
import re

# --- FONT LOADER ---
def load_custom_font(font_filename, size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    # Check system paths for DejaVu if it's not in your local folder
    return ImageFont.load_default()

# --- RANK BADGE UTILS ---
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

def get_rank_badge(rank_name_raw: str, size: int = 35): # Small & subtle
    clean = clean_rank_name(str(rank_name_raw)).upper()
    path = RANK_BADGES.get(clean)
    if not path or not os.path.exists(path):
        return None
    try:
        return Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    except:
        return None

# --- MAIN GENERATOR ---
def make_leaderboard_image(players):
    header_h = 140
    row_h = 75 
    W = 900    
    H = header_h + (len(players) * row_h) + 40
    
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # 2. FONTS
    f_title = load_custom_font("Orbitron-VariableFont_wght.ttf", 45)
    f_rank  = load_custom_font("Michroma-Regular.ttf", 22)
    # Switch to DejaVuSans-Bold for the "Big Pop" names
    f_name  = load_custom_font("DejaVuSans-Bold.ttf", 42) 
    f_pts   = load_custom_font("Michroma-Regular.ttf", 26)
    f_label = load_custom_font("Michroma-Regular.ttf", 14)

    # 3. HEADER
    draw.rectangle([(0, 0), (W, 115)], fill=(18, 18, 18))
    draw.text((40, 35), "ARENA RANKINGS", font=f_title, fill=(255, 255, 255))
    
    draw.text((40, 118), "RANK", font=f_label, fill=(100, 100, 100))
    draw.text((160, 118), "CONTENDER", font=f_label, fill=(100, 100, 100))
    draw.text((W - 180, 118), "RATING", font=f_label, fill=(100, 100, 100))

    # 4. PLAYER ROWS
    curr_y = header_h
    for i, p in enumerate(players):
        rank_num = i + 1
        color = p.get('rank_color', (255, 255, 255))
        rank_name = p.get('rank_name', "BRONZE")
        
        if i % 2 == 0:
            draw.rectangle([(15, curr_y), (W-15, curr_y + row_h - 10)], fill=(12, 12, 12))

        # Rank Number
        draw.text((45, curr_y + 18), f"#{rank_num:02d}", font=f_rank, fill=(180, 180, 180))

        # --- RANK EMBLEM (SMALLER) ---
        badge = get_rank_badge(rank_name, size=40) 
        name_x = 160
        if badge:
            # Centered vertically in the row
            card.paste(badge, (160, curr_y + 12), badge)
            name_x += 55 

        # --- DEJAVU BOLD NAME ---
        name_text = p['name'].upper()
        # Subtle name shadow for depth
        draw.text((name_x + 2, curr_y + 10), name_text, font=f_name, fill=(0, 0, 0, 200))
        draw.text((name_x, curr_y + 8), name_text, font=f_name, fill=(255, 255, 255))
        
        # Rating (Michroma - Pushed right)
        draw.text((W - 180, curr_y + 18), str(p['pts']), font=f_pts, fill=color)

        # Side Accent Glow
        if rank_num <= 3:
            draw.rectangle([(15, curr_y), (22, curr_y + row_h - 10)], fill=color)

        curr_y += row_h

    # 5. FOOTER
    draw.text((W//2, H - 20), "BATTLE DATA VERIFIED // SEASON 1", font=f_label, fill=(70, 70, 70), anchor="mm")

    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
