from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import math
import re
import os
import discord

# ==============================
# FONT LOADER
# ==============================

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


# ==============================
# RANK BADGES
# ==============================

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


def get_rank_badge(rank_name_raw: str, size: int = 40) -> Image.Image | None:
    clean = clean_rank_name(rank_name_raw).upper()
    path = RANK_BADGES.get(clean)

    if not path or not os.path.exists(path):
        return None

    try:
        return Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    except:
        return None


# ==============================
# AVATAR FETCH
# ==============================

async def fetch_avatar(url: str) -> Image.Image | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url), timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert('RGBA')
    except:
        pass
    return None


# ==============================
# PROFILE CARD GENERATOR
# ==============================

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
    print("NEW PROFILE CARD VERSION LOADED")

    # ------------------------------
    # BASE CANVAS
    # ------------------------------

    W, H = 600, 600
    CENTER_X = W // 2

    card = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # ------------------------------
    # FONTS
    # ------------------------------

    f_name   = load_safe_font(52)
    f_rank   = load_safe_font(22)
    f_label  = load_safe_font(18)
    f_value  = load_safe_font(28)
    f_pts    = load_safe_font(90)
    f_prog   = load_safe_font(18)

    # ------------------------------
    # AVATAR (Centered)
    # ------------------------------

    av_size = 180
    av_x = CENTER_X - av_size // 2
    av_y = 50

    if avatar_img:
        av = avatar_img.resize((av_size, av_size), Image.LANCZOS)
    else:
        av = Image.new('RGBA', (av_size, av_size), (40, 40, 40, 255))

    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, av_size-1, av_size-1), fill=255)

    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Rank glow ring
    ring_size = av_size + 14
    ring = Image.new('RGBA', (ring_size, ring_size), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (0, 0, ring_size-1, ring_size-1),
        outline=(*rank_color, 255),
        width=7
    )

    card.paste(ring, (av_x-7, av_y-7), ring)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Current rank badge
    cur_badge = get_rank_badge(current_rank_raw, size=55)
    if cur_badge:
        badge_x = av_x + av_size - 40
        badge_y = av_y + av_size - 40
        card.paste(cur_badge, (badge_x, badge_y), cur_badge)

    # ------------------------------
    # HEADER TEXT (Centered)
    # ------------------------------

    clean_cur = clean_rank_name(current_rank_raw)

    draw.text(
        (CENTER_X, av_y + av_size + 35),
        display_name,
        font=f_name,
        fill=(255, 255, 255),
        anchor="mm"
    )

    draw.text(
        (CENTER_X, av_y + av_size + 80),
        f"{clean_cur} · {p_title}",
        font=f_rank,
        fill=(*rank_color, 255),
        anchor="mm"
    )

    # ------------------------------
    # BALANCED GRID STATS
    # ------------------------------

    LEFT_COL_X  = CENTER_X - 200
    RIGHT_COL_X = CENTER_X + 80
    BASE_Y = 330

    LABEL_SPACING = 28
    SECTION_SPACING = 90

    label_color = (120, 120, 120)
    value_color = (255, 255, 255)

    # --- RATING
    draw.text((LEFT_COL_X, BASE_Y),
              "RATING",
              font=f_label,
              fill=label_color,
              anchor="lm")

    draw.text((LEFT_COL_X, BASE_Y + LABEL_SPACING),
              str(pts),
              font=f_pts,
              fill=(*rank_color, 255),
              anchor="lm")

    # --- RECORD
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    draw.text((RIGHT_COL_X, BASE_Y),
              "RECORD",
              font=f_label,
              fill=label_color,
              anchor="lm")

    draw.text((RIGHT_COL_X, BASE_Y + LABEL_SPACING),
              f"{wins}W {losses}L ({wr}%)",
              font=f_value,
              fill=value_color,
              anchor="lm")

    # --- STREAK
    streak_label = "🔥 STREAK" if streak >= 3 else "STREAK"

    draw.text((RIGHT_COL_X, BASE_Y + SECTION_SPACING),
              streak_label,
              font=f_label,
              fill=label_color,
              anchor="lm")

    draw.text((RIGHT_COL_X, BASE_Y + SECTION_SPACING + LABEL_SPACING),
              f"{streak} Win Streak",
              font=f_value,
              fill=value_color,
              anchor="lm")

    # --- SIGNATURE MOVE
    draw.text((LEFT_COL_X, BASE_Y + SECTION_SPACING + 20),
              "SIGNATURE MOVE",
              font=f_label,
              fill=label_color,
              anchor="lm")

    draw.text((LEFT_COL_X, BASE_Y + SECTION_SPACING + 20 + LABEL_SPACING),
              p_move,
              font=f_value,
              fill=value_color,
              anchor="lm")

    # ------------------------------
    # CENTERED PROGRESS BAR
    # ------------------------------

    bar_w = 480
    bar_h = 20
    bar_x = (W - bar_w) // 2
    bar_y = 540

    # Background
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=10,
        fill=(35, 35, 35)
    )

    # Fill
    fill_w = int(bar_w * min(pct, 1.0))

    if fill_w > 0:
        radius = min(10, fill_w // 2)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
            radius=radius,
            fill=(*rank_color, 255)
        )

    # Next rank indicator
    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text(
            (bar_x, bar_y - 22),
            f"{int(pct * 100)}% to {clean_next}",
            font=f_prog,
            fill=(160, 160, 160),
            anchor="ls"
        )

        next_badge = get_rank_badge(next_rank_raw, size=60)
        if next_badge:
            card.paste(
                next_badge,
                (bar_x + bar_w + 15, bar_y - 25),
                next_badge
            )

    # ------------------------------
    # RANK COLORED BORDER
    # ------------------------------

    draw.rectangle(
        (0, 0, W-1, H-1),
        outline=(*rank_color, 255),
        width=10
    )

    # ------------------------------
    # OUTPUT BUFFER
    # ------------------------------

    buf = io.BytesIO()
    card.save(buf, "PNG")
    buf.seek(0)
    return buf
