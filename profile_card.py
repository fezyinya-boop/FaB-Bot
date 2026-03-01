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
    card = Image.new('RGBA', (W, H), (0,0,0,
