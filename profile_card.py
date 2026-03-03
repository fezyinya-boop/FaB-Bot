from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops
import aiohttp
import io
import os
import re
from functools import lru_cache
from typing import Optional, Tuple

RGBA = Tuple[int, int, int, int]
RGB = Tuple[int, int, int]

HEADER = (185, 185, 200, 255)

# ----------------------------
# Paths
# ----------------------------
ROOT_DIR = os.path.dirname(__file__)
FONTS_DIR = os.path.join(ROOT_DIR, "fonts")
BADGES_DIR = os.path.join(ROOT_DIR, "badges")
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")

# ----------------------------
# Badges (your existing mapping)
# ----------------------------
RANK_BADGES = {
    "DIAMOND":  os.path.join(BADGES_DIR, "rank_diamond.png"),
    "PLATINUM": os.path.join(BADGES_DIR, "rank_platinum.png"),
    "GOLD":     os.path.join(BADGES_DIR, "rank_gold.png"),
    "SILVER":   os.path.join(BADGES_DIR, "rank_silver.png"),
    "BRONZE":   os.path.join(BADGES_DIR, "rank_bronze.png"),
}



# ----------------------------
# Fonts (cached)
# ----------------------------
@lru_cache(maxsize=256)
def load_font(preferred_filename: str, size: int) -> ImageFont.ImageFont:
    """Load a font from ./fonts if available, else try common system fallbacks."""
    path = os.path.join(FONTS_DIR, preferred_filename)
    if os.path.exists(path):
        return ImageFont.truetype(path, size)

    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-bold.otf",
    ):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)

    return ImageFont.load_default()

def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        return int(len(text) * (getattr(font, "size", 16) * 0.6))

def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    preferred_filename: str,
    max_w: int,
    start_size: int,
    min_size: int,
) -> ImageFont.ImageFont:
    """Shrink font size until it fits max_w."""
    size = start_size
    while size >= min_size:
        f = load_font(preferred_filename, size)
        if text_width(draw, text, f) <= max_w:
            return f
        size -= 1
    return load_font(preferred_filename, min_size)

# ----------------------------
# Image helpers
# ----------------------------
def center_crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))

def soft_circle_mask(size: int, feather: int = 4) -> Image.Image:
    """Slightly feathered circle mask for smooth avatar edges."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((feather, feather, size - feather - 1, size - feather - 1), fill=255)
    # cheap AA: upscale then downscale
    m2 = m.resize((size * 2, size * 2), Image.Resampling.BICUBIC).resize((size, size), Image.Resampling.LANCZOS)
    return m2

async def fetch_avatar(url: str) -> Optional[Image.Image]:
    """Fetch avatar image and return RGBA PIL image."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url), timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        print(f"Avatar fetch error: {e}")
    return None

# ----------------------------
# Rank helpers
# ----------------------------
def clean_rank_name(name: str) -> str:
    return re.sub(r"<:[^:]+:\d+>\s*", "", name).strip()

def get_rank_badge(rank_name_raw: str, size: int = 60) -> Optional[Image.Image]:
    clean = clean_rank_name(rank_name_raw).upper()
    path = RANK_BADGES.get(clean)
    if not path or not os.path.exists(path):
        return None
    try:
        return Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        return None

# ----------------------------
# Banner-friendly anime background
# ----------------------------
def apply_anime_arena_background(
    base: Image.Image,
    art: Image.Image,
    *,
    focus_right: bool = True,
    art_strength: float = 0.95,
    blur_px: int = 6,
    saturation: float = 1.18,
    brightness: float = 0.82,
    contrast: float = 1.08,
    tint: Tuple[int, int, int, int] = (120, 60, 180, 22),
) -> Image.Image:
    W, H = base.size
    art = art.convert("RGBA")

    # cover-fit crop, optional right bias
    aw, ah = art.size
    target_ratio = W / H
    art_ratio = aw / ah

    if art_ratio > target_ratio:
        new_w = int(ah * target_ratio)
        left = aw - new_w if focus_right else (aw - new_w) // 2
        art = art.crop((left, 0, left + new_w, ah))
    else:
        new_h = int(aw / target_ratio)
        top = (ah - new_h) // 2
        art = art.crop((0, top, aw, top + new_h))

    art = art.resize((W, H), Image.Resampling.LANCZOS)

    if blur_px > 0:
        art = art.filter(ImageFilter.GaussianBlur(radius=blur_px))

    art = ImageEnhance.Color(art).enhance(saturation)
    art = ImageEnhance.Contrast(art).enhance(contrast)
    art = ImageEnhance.Brightness(art).enhance(brightness)

    # opacity
    a = art.split()[-1].point(lambda v: int(v * art_strength))
    art.putalpha(a)

    out = Image.alpha_composite(base, art)

    # tint
    if tint and tint[3] > 0:
        out = Image.alpha_composite(out, Image.new("RGBA", (W, H), tint))

    # bloom
    bright_pass = ImageEnhance.Brightness(out).enhance(1.15).filter(ImageFilter.GaussianBlur(radius=6))
    out = ImageChops.screen(out, bright_pass)

    return out

# ----------------------------
# Main card generator (NEW layout)
# ----------------------------
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
    next_rank_raw: Optional[str],
    rank_color: RGB,
    avatar_img: Optional[Image.Image] = None,
) -> io.BytesIO:
    # Premium 2:1 output
    SCALE = 2
    OUT_W, OUT_H = 1024, 512
    W, H = OUT_W * SCALE, OUT_H * SCALE

    def S(x: int) -> int:
        return x * SCALE

    rc = rank_color
    WHITE: RGBA = (238, 236, 232, 255)
    MUTED: RGBA = (155, 155, 165, 255)
    SOFT: RGBA  = (255, 255, 255, 40)
    HEADER: RGBA = (185, 185, 200, 255)
    SUB: RGBA = (165, 165, 178, 255)

    # Base
    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # Banner
    banner_h = S(210)
    banner = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))

    bg_path = os.path.join(ASSETS_DIR, "arena_bg.png")
    if os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert("RGBA")
            banner = apply_anime_arena_background(banner, bg, focus_right=True)
        except Exception as e:
            print(f"Background overlay error: {e}")

    # Dark fade over banner (keeps header readable)
    fade = Image.new("L", (W, banner_h), 0)
    fd = ImageDraw.Draw(fade)
    fd.rectangle((0, 0, W, banner_h), fill=180)
    fade = fade.filter(ImageFilter.GaussianBlur(radius=S(18)))
    fade_rgba = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))
    fade_rgba.putalpha(fade)
    banner = Image.alpha_composite(banner, fade_rgba)

    card.paste(banner, (0, 0), banner)

    # Info panel (solid glass)
    panel_y = banner_h - S(28)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)

    panel_pad_l = S(280)
    panel_pad_r = S(26)
    panel_pad_t = panel_y + S(18)
    panel_pad_b = H - S(26)

    pd.rounded_rectangle(
        (panel_pad_l, panel_pad_t, W - panel_pad_r, panel_pad_b),
        radius=S(26),
        fill=(0, 0, 0, 210),
        outline=(255, 255, 255, 26),
        width=S(2),
    )
    pd.rectangle((0, panel_y, W, panel_y + S(2)), fill=(255, 255, 255, 18))

    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # Avatar (overlaps)
    av_size = S(240)
    av_x = S(38)
    av_y = S(78)

    if avatar_img is None:
        avatar_img = Image.new("RGBA", (av_size, av_size), (25, 25, 28, 255))
    else:
        avatar_img = center_crop_square(avatar_img.convert("RGBA"))

    av = avatar_img.resize((av_size, av_size), Image.Resampling.LANCZOS)

    # Glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx = av_x + av_size // 2
    gy = av_y + av_size // 2
    for r in range(S(190), 0, -S(10)):
        a = int(55 * (1 - r / S(190)) ** 2)
        gd.ellipse((gx - r, gy - r, gx + r, gy + r), fill=(rc[0], rc[1], rc[2], a))
    card = Image.alpha_composite(card, glow)
    draw = ImageDraw.Draw(card)

    mask = soft_circle_mask(av_size, feather=S(2))
    av_circ = Image.new("RGBA", (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, (0, 0), mask=mask)

    ring_rect = (av_x - S(6), av_y - S(6), av_x + av_size + S(6), av_y + av_size + S(6))
    draw.ellipse(ring_rect, outline=(rc[0], rc[1], rc[2], 230), width=S(5))
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Rank badge overlap
    badge_size = S(78)
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        bx = av_x + av_size - S(58)
        by = av_y + av_size - S(58)
        card.paste(cur_badge, (bx, by), cur_badge)

    # Panel columns
    col_left = panel_pad_l + S(28)
    col_right = W - panel_pad_r - S(28)
    col_mid = col_left + int((col_right - col_left) * 0.62)

    # Fonts (your hard-coded filenames)
    name_text = (display_name or "PLAYER").upper()
    move_text = (p_move or "").upper()

    f_name = fit_font(draw, name_text, "Orbitron-VariableFont_wght.ttf", max_w=col_right - col_left, start_size=S(46), min_size=S(28))
    f_big  = load_font("Michroma-Regular.ttf", S(76))
    f_h2   = load_font("DejaVuSans-Bold.ttf", S(24))
    f_lab   = load_font("FunnelSans-VariableFont_wght.ttf", S(18))  # headers
    f_small = load_font("FunnelSans-VariableFont_wght.ttf", S(14))  # helper text
    f_val   = load_font("DejaVuSans-Bold.ttf", S(24))               # values stay bold & punchy
    f_move = fit_font(
     draw,
     move_text,
     "FunnelSans-VariableFont_wght.ttf",
     max_w=col_right - col_left,
     start_size=S(28),
     min_size=S(16),
    )
    # Header on banner aligned to panel
    header_y = S(36)
    stroke = (0, 0, 0, 200)

    draw.text((col_left, header_y), name_text, font=f_name, fill=WHITE, stroke_width=S(2), stroke_fill=stroke)

    clean_cur = clean_rank_name(current_rank_raw)
    header2_y = header_y + S(58)
    draw.text((col_left, header2_y), clean_cur, font=f_h2, fill=(rc[0], rc[1], rc[2], 255), stroke_width=S(2), stroke_fill=stroke)
    rank_w = text_width(draw, clean_cur, f_h2)
    draw.text((col_left + rank_w + S(12), header2_y + S(2)), "·", font=f_h2, fill=(255, 255, 255, 170), stroke_width=S(2), stroke_fill=stroke)
    draw.text((col_left + rank_w + S(30), header2_y), (p_title or ""), font=f_h2, fill=WHITE, stroke_width=S(2), stroke_fill=stroke)

    # Content
    content_top = panel_pad_t + S(26)

# Header color (define once above this block if you haven't already)
# HEADER = (185, 185, 200, 255)

# --- RATING (left)
    draw.text((col_left, content_top), "RATING", font=f_lab, fill=HEADER)
    draw.text(
    (col_left, content_top + S(28)),
    str(pts),
    font=f_big,
    fill=(rc[0], rc[1], rc[2], 255),
    stroke_width=S(2),
    stroke_fill=(0, 0, 0, 160),
    )

# --- RECORD + STREAK (right)
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    right_x = col_mid + S(22)

    draw.text((right_x, content_top), "RECORD", font=f_lab, fill=HEADER)
    draw.text(
    (right_x, content_top + S(28)),
    f"{wins}W – {losses}L",
    font=f_val,
    fill=WHITE,
    stroke_width=S(2),
    stroke_fill=(0, 0, 0, 150),
    )

    SUB = (165, 165, 178, 255)  # slightly nicer than MUTED for helper text
    draw.text((right_x, content_top + S(62)), f"{wr}% win rate", font=f_small, fill=SUB)

    draw.text((right_x, content_top + S(102)), "STREAK", font=f_lab, fill=HEADER)
    streak_col = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    streak_label = f"{streak} Wins 🔥" if streak >= 3 else f"{streak} Wins"
    draw.text(
    (right_x, content_top + S(130)),
    streak_label,
    font=f_val,
    fill=streak_col,
    stroke_width=S(2),
    stroke_fill=(0, 0, 0, 150),
    )

# --- SIGNATURE MOVE (bottom)
    div_y = content_top + S(210)
    draw.line([(col_left, div_y), (col_right, div_y)], fill=SOFT, width=S(2))

    draw.text((col_left, div_y + S(16)), "SIGNATURE MOVE", font=f_lab, fill=HEADER)
    move_display = move_text if move_text.strip() else "NONE SET"
    move_fill = WHITE if move_text.strip() else SUB
    draw.text(
    (col_left, div_y + S(44)),
    move_display,
    font=f_move,
    fill=move_fill,
    stroke_width=S(2),
    stroke_fill=(0, 0, 0, 170),
    )
    # Progress
    bar_y = panel_pad_b - S(58)
    pct_clamped = max(0.0, min(1.0, float(pct)))

    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((col_left, bar_y - S(22)), f"{int(pct_clamped * 100)}% to {clean_next}", font=f_small, fill=MUTED)
    else:
        draw.text((col_left, bar_y - S(22)), "MAX RANK REACHED", font=f_small, fill=(rc[0], rc[1], rc[2], 255))

    badge_slot = S(56)
    bar_w = (col_right - col_left) - badge_slot - S(10)
    bar_h = S(12)

    draw.rounded_rectangle((col_left, bar_y, col_left + bar_w, bar_y + bar_h), radius=S(8), fill=(28, 28, 34, 255))
    fill_w = int(bar_w * pct_clamped)
    if fill_w > 0:
        draw.rounded_rectangle((col_left, bar_y, col_left + fill_w, bar_y + bar_h), radius=S(8), fill=(rc[0], rc[1], rc[2], 255))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(6))
        if next_badge:
            card.paste(next_badge, (col_left + bar_w + S(14), bar_y + bar_h // 2 - (badge_slot - S(6)) // 2), next_badge)

    # Final downscale
    final = card.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    final.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
