from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os
import re

# --- FONT LOADER ---
def load_custom_font(font_filename, size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()

# --- HELPERS ---
def clean_rank_name(name: str) -> str:
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

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
    # --- 1. RECTANGULAR SETUP (16:9 ish) ---
    W, H = 800, 450
    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # --- 2. FONT ASSIGNMENT ---
    # Name: Orbitron (Variable Font)
    f_name  = load_custom_font("Orbitron-VariableFont_wght.ttf", 60)
    
    # Headers/Rating: Michroma
    f_pts   = load_custom_font("Michroma-Regular.ttf", 85)
    f_label = load_custom_font("Michroma-Regular.ttf", 14)
    
    # Sub-text: Pirata One (Using it for Title for a unique accent)
    f_title = load_custom_font("PirataOne-Regular.ttf", 40)
    
    # Stats: Funnel Sans
    f_value = load_custom_font("FunnelSans-Regular.ttf", 28)
    f_prog  = load_custom_font("FunnelSans-Light.ttf", 16)

    # --- 3. LEFT-SIDE AVATAR ---
    av_size = 220
    av_x, av_y = 40, (H - av_size) // 2
    
    if avatar_img:
        av = avatar_img.resize((av_size, av_size))
    else:
        av = Image.new('RGBA', (av_size, av_size), (30, 30, 30, 255))

    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size, av_size)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Thick Avatar Ring
    draw.ellipse([(av_x-10, av_y-10), (av_x+av_size+10, av_y+av_size+10)], outline=(*rank_color, 255), width=12)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # --- 4. MAIN CONTENT (Right Side) ---
    content_x = av_x + av_size + 50
    
    # Name (Orbitron)
    draw.text((content_x, 60), display_name.upper(), font=f_name, fill=(255, 255, 255))
    
    # Title (Pirata One - looks like a cool stamp under the name)
    draw.text((content_x, 130), p_title, font=f_title, fill=(*rank_color, 255))

    # --- 5. STATS GRID ---
    # Rating (Michroma)
    draw.text((content_x, 190), "RATING", font=f_label, fill=(100, 100, 100))
    draw.text((content_x, 210), str(pts), font=f_pts, fill=(*rank_color, 255))

    # Battle Stats
    stat_col_2 = content_x + 240
    
    draw.text((stat_col_2, 210), "RECORD", font=f_label, fill=(100, 100, 100))
    draw.text((stat_col_2, 235), f"{wins}W - {losses}L", font=f_value, fill=(255, 255, 255))
    
    streak_lbl = "🔥 STREAK" if streak >= 3 else "STREAK"
    draw.text((stat_col_2, 280), streak_lbl, font=f_label, fill=(100, 100, 100))
    draw.text((stat_col_2, 305), f"{streak} Wins", font=f_value, fill=(255, 255, 255))

    # Signature Move
    draw.text((content_x, 320), "SIGNATURE MOVE", font=f_label, fill=(100, 100, 100))
    draw.text((content_x, 345), p_move.upper(), font=f_value, fill=(255, 255, 255))

    # --- 6. PROGRESS BAR (Full Width at Bottom) ---
    bar_x, bar_y = content_x, 400
    bar_w, bar_h = 420, 10
    draw.rectangle([(bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h)], fill=(40, 40, 40))
    
    fill_w = int(bar_w * min(pct, 1.0))
    draw.rectangle([(bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h)], fill=(*rank_color, 255))
    
    draw.text((bar_x, bar_y - 20), f"{int(pct*100)}% TO NEXT RANK", font=f_prog, fill=(150, 150, 150))

    # --- 7. EXPORT ---
    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
