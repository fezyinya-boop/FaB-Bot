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

# ----------------------------
# Paths
# ----------------------------
ROOT_DIR = os.path.dirname(__file__)
FONTS_DIR = os.path.join(ROOT_DIR, "fonts")
BADGES_DIR = os.path.join(ROOT_DIR, "badges")
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")

# ----------------------------
# Badges
# ----------------------------
RANK_BADGES = {
    "DIAMOND": os.path.join(BADGES_DIR, "rank_diamond.png"),
    "PLATINUM": os.path.join(BADGES_DIR, "rank_platinum.png"),
    "GOLD": os.path.join(BADGES_DIR, "rank_gold.png"),
    "SILVER": os.path.join(BADGES_DIR, "rank_silver.png"),
    "BRONZE": os.path.join(BADGES_DIR, "rank_bronze.png"),
}

# ----------------------------
# Fonts
# ----------------------------
@lru_cache(maxsize=256)
def load_font(preferred_filename: str, size: int) -> ImageFont.ImageFont:
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
    if text_width(draw, text, font) <= max_w:
        return text
    ell = "…"
    t = text
    while t and text_width(draw, t + ell, font) > max_w:
        t = t[:-1]
    return (t + ell) if t else ell



def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int, max_lines: int = 3) -> list[str]:
    text = (text or '').strip()
    if not text:
        return ['']

    tokens = text.split()
    # Handle single long unbroken strings by chunking by characters.
    if len(tokens) <= 1:
        chars = list(text)
        lines = []
        current = ''
        for ch in chars:
            trial = current + ch
            if current and text_width(draw, trial, font) > max_w:
                lines.append(current)
                current = ch
                if len(lines) >= max_lines - 1:
                    break
            else:
                current = trial
        if len(lines) < max_lines and current:
            remaining = ''.join(chars[len(''.join(lines) + current):])
            if remaining:
                current += remaining
            lines.append(current)
        lines = lines[:max_lines]
        if len(lines) == max_lines:
            lines[-1] = clamp_text(draw, lines[-1], font, max_w)
        return lines

    lines = []
    current = tokens[0]
    for word in tokens[1:]:
        trial = current + ' ' + word
        if text_width(draw, trial, font) <= max_w:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break

    if len(lines) < max_lines:
        consumed = len(' '.join(lines).split())
        remaining_words = tokens[consumed:]
        if remaining_words:
            current = ' '.join(remaining_words)
        lines.append(current)

    lines = lines[:max_lines]
    if len(lines) == max_lines:
        lines[-1] = clamp_text(draw, lines[-1], font, max_w)
    return lines

def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    preferred_filename: str,
    max_w: int,
    start_size: int,
    min_size: int,
) -> ImageFont.ImageFont:
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
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((feather, feather, size - feather - 1, size - feather - 1), fill=255)
    return m.resize((size * 2, size * 2), Image.Resampling.BICUBIC).resize((size, size), Image.Resampling.LANCZOS)


async def fetch_avatar(url: str) -> Optional[Image.Image]:
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
# Background helper
# ----------------------------
def apply_anime_arena_background(
    base: Image.Image,
    art: Image.Image,
    *,
    focus_right: bool = True,
    art_strength: float = 0.9,
    blur_px: int = 7,
    saturation: float = 1.12,
    brightness: float = 0.78,
    contrast: float = 1.1,
    tint: Tuple[int, int, int, int] = (110, 70, 180, 18),
) -> Image.Image:
    w, h = base.size
    art = art.convert("RGBA")

    aw, ah = art.size
    target_ratio = w / h
    art_ratio = aw / ah

    if art_ratio > target_ratio:
        new_w = int(ah * target_ratio)
        left = aw - new_w if focus_right else (aw - new_w) // 2
        art = art.crop((left, 0, left + new_w, ah))
    else:
        new_h = int(aw / target_ratio)
        top = (ah - new_h) // 2
        art = art.crop((0, top, aw, top + new_h))

    art = art.resize((w, h), Image.Resampling.LANCZOS)
    if blur_px > 0:
        art = art.filter(ImageFilter.GaussianBlur(radius=blur_px))

    art = ImageEnhance.Color(art).enhance(saturation)
    art = ImageEnhance.Contrast(art).enhance(contrast)
    art = ImageEnhance.Brightness(art).enhance(brightness)

    a = art.split()[-1].point(lambda v: int(v * art_strength))
    art.putalpha(a)

    out = Image.alpha_composite(base, art)
    if tint and tint[3] > 0:
        out = Image.alpha_composite(out, Image.new("RGBA", (w, h), tint))

    bloom = ImageEnhance.Brightness(out).enhance(1.15).filter(ImageFilter.GaussianBlur(radius=6))
    return ImageChops.screen(out, bloom)


# ----------------------------
# Main card generator
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
    SCALE = 2
    OUT_W, OUT_H = 1024, 512
    W, H = OUT_W * SCALE, OUT_H * SCALE

    def S(x: int) -> int:
        return x * SCALE

    rc = rank_color
    WHITE: RGBA = (242, 242, 245, 255)
    OFF_WHITE: RGBA = (220, 220, 228, 255)
    MUTED: RGBA = (145, 148, 160, 255)
    SUB: RGBA = (170, 173, 184, 255)
    GOLD: RGBA = (255, 214, 96, 255)
    PANEL_FILL: RGBA = (8, 8, 12, 228)
    PANEL_LINE: RGBA = (255, 255, 255, 22)
    STROKE: RGBA = (0, 0, 0, 185)

    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # Top cinematic banner
    banner_h = S(205)
    banner = Image.new("RGBA", (W, banner_h), (6, 6, 10, 255))
    bg_path = os.path.join(ASSETS_DIR, "arena_bg.png")
    if os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert("RGBA")
            banner = apply_anime_arena_background(banner, bg, focus_right=True)
        except Exception as e:
            print(f"Background overlay error: {e}")

    fade = Image.new("L", (W, banner_h), 0)
    fd = ImageDraw.Draw(fade)
    fd.rectangle((0, 0, W, banner_h), fill=185)
    fade = fade.filter(ImageFilter.GaussianBlur(radius=S(18)))
    fade_rgba = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))
    fade_rgba.putalpha(fade)
    banner = Image.alpha_composite(banner, fade_rgba)
    card.paste(banner, (0, 0), banner)

    # Main panel
    panel_y = banner_h - S(30)
    panel_x1 = S(260)
    panel_x2 = W - S(26)
    panel_y2 = H - S(24)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle(
        (panel_x1, panel_y, panel_x2, panel_y2),
        radius=S(28),
        fill=PANEL_FILL,
        outline=PANEL_LINE,
        width=S(2),
    )
    pd.rounded_rectangle((S(28), panel_y + S(18), panel_x1 - S(24), panel_y2), radius=S(28), fill=(12, 12, 16, 214), outline=PANEL_LINE, width=S(2))
    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # Subtle interior accent for depth
    accent = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent)
    ad.rounded_rectangle((panel_x1 + S(14), panel_y + S(14), panel_x2 - S(14), panel_y + S(78)), radius=S(22), fill=(255, 255, 255, 8))
    ad.line((panel_x1 + S(26), panel_y + S(96), panel_x2 - S(26), panel_y + S(96)), fill=(255, 255, 255, 12), width=S(2))
    accent = accent.filter(ImageFilter.GaussianBlur(radius=S(2)))
    card = Image.alpha_composite(card, accent)
    draw = ImageDraw.Draw(card)

    # Avatar block
    av_size = S(174)
    av_x = S(50)
    av_y = S(58)
    if avatar_img is None:
        avatar_img = Image.new("RGBA", (av_size, av_size), (28, 28, 34, 255))
    else:
        avatar_img = center_crop_square(avatar_img.convert("RGBA"))

    av = avatar_img.resize((av_size, av_size), Image.Resampling.LANCZOS)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = av_x + av_size // 2
    cy = av_y + av_size // 2
    for r in range(S(210), 0, -S(12)):
        a = int(48 * (1 - r / S(210)) ** 2)
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(rc[0], rc[1], rc[2], a))
    card = Image.alpha_composite(card, glow)
    draw = ImageDraw.Draw(card)

    mask = soft_circle_mask(av_size, feather=S(2))
    av_circ = Image.new("RGBA", (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, (0, 0), mask=mask)
    draw.ellipse((av_x - S(7), av_y - S(7), av_x + av_size + S(7), av_y + av_size + S(7)), outline=(rc[0], rc[1], rc[2], 230), width=S(5))
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Typography
    col_left = panel_x1 + S(28)
    col_right = panel_x2 - S(26)
    name_text = (display_name or "PLAYER").upper()
    title_text = (p_title or "COMPETITOR").upper()
    bio_label = "BIO :"

    f_name = fit_font(draw, name_text, "RussoOne-Regular.ttf", max_w=col_right - col_left - S(40), start_size=S(56), min_size=S(30))
    f_title = load_font("Inter-VariableFont_opsz,wght.ttf", S(24))
    f_brand = load_font("Inter-VariableFont_opsz,wght.ttf", S(18))
    f_label = load_font("Inter-VariableFont_opsz,wght.ttf", S(22))
    f_small = load_font("Inter-VariableFont_opsz,wght.ttf", S(15))
    f_value = load_font("Orbitron-VariableFont_wght.ttf", S(30))
    f_big = fit_font(draw, f"{pts} RP", "Orbitron-VariableFont_wght.ttf", max_w=S(420), start_size=S(68), min_size=S(42))

    # Header content
    header_y = S(34)
    draw_tracked(draw, (col_left, header_y), name_text, f_name, WHITE, S(2), stroke_width=S(2), stroke_fill=STROKE)

    badge = get_rank_badge(current_rank_raw, size=S(46))
    badge_x = col_left
    header2_y = header_y + S(70)
    if badge:
        card.paste(badge, (badge_x, header2_y - S(3)), badge)
        title_x = badge_x + badge.size[0] + S(22)
    else:
        title_x = badge_x

    draw.text((title_x, header2_y), title_text, font=f_title, fill=WHITE, stroke_width=S(2), stroke_fill=STROKE)

    # Left bio block
    sig_x = av_x + S(6)
    sig_y = av_y + av_size + S(56)
    sig_w = (panel_x1 - S(44)) - sig_x
    sig_h = S(112)
    draw.rounded_rectangle((sig_x, sig_y - S(10), sig_x + sig_w, sig_y + sig_h), radius=S(18), fill=(16, 16, 22, 210), outline=PANEL_LINE, width=S(2))
    draw_tracked(draw, (sig_x + S(16), sig_y + S(6)), bio_label, f_small, OFF_WHITE, S(2), stroke_width=S(1), stroke_fill=(0, 0, 0, 160))

    move_text = (p_move or "None set").strip()
    text_max_w = sig_w - S(32)
    f_move = fit_font(draw, move_text, "Inter-VariableFont_opsz,wght.ttf", text_max_w, S(19), S(12))
    move_lines = wrap_text(draw, move_text, f_move, text_max_w, max_lines=4)
    line_h = max(S(17), (getattr(f_move, "size", S(14)) + S(3)))
    text_y = sig_y + S(40)
    for line in move_lines:
        draw.text((sig_x + S(16), text_y), line, font=f_move, fill=WHITE if p_move else SUB, stroke_width=S(1), stroke_fill=(0, 0, 0, 150))
        text_y += line_h

    # Stat grid
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0
    content_top = panel_y + S(16)
    left_x = col_left
    right_x = col_left + int((col_right - col_left) * 0.70)
    row1_y = content_top + S(18)
    row2_y = content_top + S(122)

    def stat_block(x: int, y: int, label: str, value: str, *, value_font: ImageFont.ImageFont, value_fill: RGBA = WHITE, subtext: Optional[str] = None) -> int:
        if label:
            draw_tracked(draw, (x, y), label, f_label, OFF_WHITE, S(3), stroke_width=S(1), stroke_fill=(0, 0, 0, 185))
        value_y = y + (S(34) if label else 0)
        draw.text((x, value_y), value, font=value_font, fill=value_fill, stroke_width=S(2), stroke_fill=(0, 0, 0, 155))
        vb = draw.textbbox((x, value_y), value, font=value_font, stroke_width=S(2))
        bottom_y = vb[3]
        if subtext:
            sub_y = bottom_y + S(6)
            draw.text((x, sub_y), subtext, font=f_small, fill=SUB, stroke_width=S(1), stroke_fill=(0, 0, 0, 120))
            sb = draw.textbbox((x, sub_y), subtext, font=f_small, stroke_width=S(1))
            bottom_y = sb[3]
        return bottom_y

    # RP glow
    rp_glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rgd = ImageDraw.Draw(rp_glow)
    rp_box_y = row1_y + S(34)
    rgd.rounded_rectangle((left_x - S(10), rp_box_y - S(6), left_x + S(330), rp_box_y + S(76)), radius=S(18), fill=(rc[0], rc[1], rc[2], 18))
    rp_glow = rp_glow.filter(ImageFilter.GaussianBlur(radius=S(8)))
    card = Image.alpha_composite(card, rp_glow)
    draw = ImageDraw.Draw(card)

    stat_block(left_x, row1_y, "RATING", f"{pts} RP", value_font=f_big, value_fill=(rc[0], rc[1], rc[2], 255))
    draw.line((left_x, row1_y + S(126), left_x + S(360), row1_y + S(126)), fill=(rc[0], rc[1], rc[2], 48), width=S(2))
    stat_block(right_x, row1_y, "RECORD", f"{wins}W – {losses}L", value_font=f_value, subtext=f"{wr}% win rate")
    streak_fill = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    streak_text = f"+{streak}" if streak > 0 else str(streak)
    stat_block(right_x, row2_y + S(18), "STREAK", streak_text, value_font=f_value, value_fill=streak_fill)

    # Progress/footer strip
    pct_clamped = max(0.0, min(1.0, float(pct)))
    footer_label = "Archive Arena • Season 1"

    badge_slot = S(54)
    bar_w = (col_right - col_left) - badge_slot - S(18)
    bar_h = S(12)
    bar_y = panel_y2 - S(44)
    label_y = bar_y - S(24)
    draw.text((col_left, label_y), footer_label, font=f_small, fill=WHITE, stroke_width=S(1), stroke_fill=(0, 0, 0, 120))
    draw.rounded_rectangle((col_left, bar_y, col_left + bar_w, bar_y + bar_h), radius=S(8), fill=(28, 28, 34, 255))
    fill_w = max(S(14), int(bar_w * pct_clamped)) if pct_clamped > 0 else 0
    if fill_w > 0:
        draw.rounded_rectangle((col_left, bar_y, col_left + fill_w, bar_y + bar_h), radius=S(8), fill=(rc[0], rc[1], rc[2], 255))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(4))
        if next_badge:
            card.paste(next_badge, (col_left + bar_w + S(18), bar_y + bar_h // 2 - next_badge.size[1] // 2), next_badge)

    # bottom edge vignette
    vignette = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse((-S(160), -S(120), W + S(160), H + S(200)), fill=220)
    vignette = ImageChops.invert(vignette).filter(ImageFilter.GaussianBlur(radius=S(42)))
    vg = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    vg.putalpha(vignette)
    card = Image.alpha_composite(card, vg)

    final = card.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    final.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
