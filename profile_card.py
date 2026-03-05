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

def clamp_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    """Clamp text to max_w with an ellipsis if needed."""
    t = text
    if text_width(draw, t, font) <= max_w:
        return t
    ell = '…'
    # Trim until it fits (leave room for ellipsis)
    while t and text_width(draw, t + ell, font) > max_w:
        t = t[:-1]
    return (t + ell) if t else ell

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


def draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGBA,
    tracking: int,
    *,
    stroke_width: int = 0,
    stroke_fill: Optional[RGBA] = None,
) -> None:
    """Draw text with simple letter-spacing (tracking)."""
    x, y = xy
    if tracking <= 0 or len(text) <= 1:
        draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return

    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += text_width(draw, ch, font) + tracking

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
    HEADER: RGBA = (210, 210, 222, 255)
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

    panel_pad_l = S(260)  # tuned for slightly smaller avatar
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

    # Avatar (top-left, slightly smaller to feel more "esports UI" and free space)
    av_size = S(176)
    av_x = S(42)
    av_y = S(56)

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

    # Panel columns
    col_left = panel_pad_l + S(28)
    col_right = W - panel_pad_r - S(28)
    col_mid = col_left + int((col_right - col_left) * 0.50)

    # Fonts (upgrade: Russo / Inter / Orbitron)
    name_text = (display_name or "PLAYER").upper()
    move_text = (p_move or "").upper()

    f_name  = fit_font(draw, name_text, "RussoOne-Regular.ttf", max_w=col_right - col_left, start_size=S(56), min_size=S(30))
    f_big   = load_font("Orbitron-VariableFont_wght.ttf", S(72))
    f_h2    = load_font("Inter-VariableFont_opsz,wght.ttf", S(24))
    # Slightly larger + brighter labels to improve readability
    f_lab   = load_font("Inter-VariableFont_opsz,wght.ttf", S(24))
    f_small = load_font("Inter-VariableFont_opsz,wght.ttf", S(18))
    f_brand = load_font("Inter-VariableFont_opsz,wght.ttf", S(20))
    f_val   = load_font("Orbitron-VariableFont_wght.ttf", S(30))
    f_move  = fit_font(
        draw,
        move_text,
        "Inter-VariableFont_opsz,wght.ttf",
        max_w=col_right - col_left,
        start_size=S(26),
        min_size=S(16),
    )

    # Signature Move block (use the dead space under avatar, make it feel premium)
    sig_x = av_x
    sig_y = av_y + av_size + S(18)
    sig_w = (panel_pad_l - S(120)) - sig_x  # keep Bio text inside left gutter
    if sig_w > S(140):
        # Divider line
        draw.rounded_rectangle(
            (sig_x, sig_y - S(10), sig_x + sig_w, sig_y - S(8)),
            radius=S(2),
            fill=(255, 255, 255, 28),
        )

        draw_tracked(
            draw,
            (sig_x, sig_y),
            "BIO:",
            font=f_lab,
            fill=HEADER,
            tracking=S(2),
            stroke_width=S(1),
            stroke_fill=(0, 0, 0, 175),
        )

        move_display = move_text.strip()
        if not move_display:
            move_display = "NONE SET"
            move_fill = SUB
        else:
            # Quote style reads as a player tagline
            move_display = f"“{move_display}”"
            move_fill = WHITE

        f_move_gutter = fit_font(
            draw,
            move_display,
            "Inter-VariableFont_opsz,wght.ttf",
            max_w=sig_w,
            start_size=S(22),
            min_size=S(14),
        )
        move_display = clamp_text(draw, move_display, f_move_gutter, sig_w)

        # Center text in the gutter
        mw = text_width(draw, move_display, f_move_gutter)
        mx = sig_x + max(0, (sig_w - mw) // 2)
        draw.text(
            (mx, sig_y + S(34)),
            move_display,
            font=f_move_gutter,
            fill=move_fill,
            stroke_width=S(2),
            stroke_fill=(0, 0, 0, 170),
        )
    # Header on banner aligned to panel
    header_y = S(34)
    stroke = (0, 0, 0, 200)

    draw_tracked(
        draw,
        (col_left, header_y),
        name_text,
        font=f_name,
        fill=WHITE,
        tracking=S(2),
        stroke_width=S(2),
        stroke_fill=stroke,
    )

    # Rank emblem + title (replace rank text with badge)
    header2_y = header_y + S(74)
    badge = get_rank_badge(current_rank_raw, size=S(48))
    badge_x = col_left
    if badge:
        card.paste(badge, (badge_x, header2_y - S(2)), badge)
        title_x = badge_x + badge.size[0] + S(28)
    else:
        title_x = badge_x

    # Subtitle line (keeps prestige without duplicating rank text)
    draw.text(
        (title_x, header2_y),
        (p_title or "").upper(),
        font=f_h2,
        fill=WHITE,
        stroke_width=S(2),
        stroke_fill=stroke,
    )

    # Small brand line under title (clean esports vibe)
    brand_y = header2_y + S(30)
    draw.text(
        (title_x, brand_y),
        "Archive Arena • Season 1",
        font=f_brand,
        fill=(255, 255, 255),
        stroke_width=S(2),
        stroke_fill=(0, 0, 190),
    )

    # Content

    content_top = panel_pad_t + S(26)

# Header color (define once above this block if you haven't already)
# HEADER = (185, 185, 200, 255)

    # --- 2x2 Stat Grid (clean competitive UI)
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    # Grid geometry
    grid_left_x = col_left
    grid_right_x = col_left + int((col_right - col_left) * 0.66)
    row1_y = content_top
    row2_y = content_top + S(128)

    # RATING (top-left)
    draw_tracked(draw, (grid_left_x, row1_y), "RATING", font=f_lab, fill=HEADER, tracking=S(3), stroke_width=S(1), stroke_fill=(0, 0, 0, 180))
    draw.text(
        (grid_left_x, row1_y + S(30)),
        f"{pts} RP",
        font=f_big,
        fill=(rc[0], rc[1], rc[2], 255),
        stroke_width=S(2),
        stroke_fill=(0, 0, 0, 160),
    )

    # RECORD (top-right)
    draw_tracked(draw, (grid_right_x, row1_y), "RECORD", font=f_lab, fill=HEADER, tracking=S(3), stroke_width=S(1), stroke_fill=(0, 0, 0, 180))
    draw.text(
        (grid_right_x, row1_y + S(34)),
        f"{wins}W – {losses}L",
        font=f_val,
        fill=WHITE,
        stroke_width=S(2),
        stroke_fill=(0, 0, 0, 150),
    )

    

    # STREAK (bottom-right)
    draw_tracked(draw, (grid_right_x, row2_y), "STREAK", font=f_lab, fill=HEADER, tracking=S(3), stroke_width=S(1), stroke_fill=(0, 0, 0, 180))
    streak_col = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    draw.text(
        (grid_right_x, row2_y + S(40)),
        f"+{streak}" if streak > 0 else str(streak),
        font=f_val,
        fill=streak_col,
        stroke_width=S(2),
        stroke_fill=(0, 0, 0, 150),
    )

    # helper text under record
    draw.text((grid_right_x, row1_y + S(98)), f"{wr}% win rate", font=f_small, fill=SUB)

    # Progress
    bar_y = panel_pad_b - S(28)  # keep progress bar low to avoid overlapping stats
    pct_clamped = max(0.0, min(1.0, float(pct)))

    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        pct_txt = f"{int(pct_clamped * 100)}%"
        rest_txt = f" to {clean_next}"
        draw.text((col_left, bar_y - S(22)), pct_txt, font=f_small, fill=(255, 215, 80, 255))
        draw.text((col_left + text_width(draw, pct_txt, f_small), bar_y - S(22)), rest_txt, font=f_small, fill=MUTED)
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
