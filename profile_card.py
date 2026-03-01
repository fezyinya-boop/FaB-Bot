from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os
import re

def load_custom_font(font_filename, size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()

def clean_rank_name(name: str) -> str:
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

# --- BADGE LOADER ---
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

def make_profile_card(
    display_name, p_title, p_move, pts, wins, losses, streak, pct,
    current_rank_raw, next_rank_raw, rank_color, avatar_img=None
):
    # --- 1. SETUP ---
    W, H = 800, 420 
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # --- 2. FONTS ---
    f_name  = load_custom_font("Orbitron-VariableFont_wght.ttf", 55)
    f_pts   = load_custom_font("Michroma-Regular.ttf", 80)
    f_label = load_custom_font("Michroma-Regular.ttf", 14)
    f_title = load_custom_font("PirataOne-Regular.ttf", 38) 
    f_value = load_custom_font("FunnelSans-Regular.ttf", 26)
    f_prog  = load_custom_font("FunnelSans-Light.ttf", 15)

    # --- 3. AVATAR & RANK EMBLEM ---
    av_size = 210
    av_x, av_y = 40, (H - av_size) // 2 - 20
    
    if avatar_img:
        av = avatar_img.resize((av_size, av_size))
    else:
        av = Image.new('RGBA', (av_size, av_size), (30, 30, 30, 255))

    # Masking for circular PFP
    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size, av_size)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Main Avatar Ring
    draw.ellipse([(av_x-8, av_y-8), (av_x+av_size+8, av_y+av_size+8)], outline=(*rank_color, 255), width=8)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # --- THE DISCORD-STYLE RANK EMBLEM ---
    # Placed at bottom right of the circle
    badge_size = 75
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        # Positioning: x = end of avatar - badge offset, y = end of avatar - badge offset
        badge_x = av_x + av_size - 60
        badge_y = av_y + av_size - 60
        
        # Optional: Subtle black border around the badge to make it "cut" the avatar
        draw.ellipse([(badge_x-4, badge_y-4), (badge_x+badge_size+4, badge_y+badge_size+4)], fill=(0,0,0,255))
        card.paste(cur_badge, (badge_x, badge_y), cur_badge)

    # --- 4. DATA COLUMNS ---
    col_rating_x = 300 
    col_stats_x  = 560 
    
    # Player ID Header
    draw.text((col_rating_x, 45), display_name.upper(), font=f_name, fill=(255, 255, 255))
    draw.text((col_rating_x, 105), p_title, font=f_title, fill=(*rank_color, 255))

    # Rating
    draw.text((col_rating_x, 185), "RATING", font=f_label, fill=(100, 100, 100))
    draw.text((col_rating_x, 205), str(pts), font=f_pts, fill=(*rank_color, 255))

    # Record & Streak
    draw.text((col_stats_x, 190), "BATTLE RECORD", font=f_label, fill=(100, 100, 100))
    draw.text((col_stats_x, 215), f"{wins}W - {losses}L", font=f_value, fill=(255, 255, 255))
    
    draw.text((col_stats_x, 265), "WIN STREAK", font=f_label, fill=(100, 100, 100))
    draw.text((col_stats_x, 290), f"{streak} Wins", font=f_value, fill=(255, 255, 255))

    # Signature Move
    draw.text((col_rating_x, 300), "SIGNATURE MOVE", font=f_label, fill=(100, 100, 100))
    draw.text((col_rating_x, 325), p_move.upper(), font=f_value, fill=(255, 255, 255))

    # --- 5. PROGRESS BAR ---
    bar_x, bar_y = col_rating_x, 385
    bar_w, bar_h = 460, 12
    draw.rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], fill=(40, 40, 40))
    
    fill_w = int(bar_w * min(pct, 1.0))
    draw.rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], fill=(*rank_color, 255))
    
    draw.text((bar_x, bar_y - 20), f"{int(pct*100)}% TO NEXT RANK", font=f_prog, fill=(150, 150, 150))

    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
