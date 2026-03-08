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



@lru_cache(maxsize=64)
def load_cinzel_font(size: int) -> ImageFont.ImageFont:
    for preferred in ("Cinzel-Black.ttf", "Cinzel-ExtraBold.ttf", "Cinzel-Bold.ttf"):
        path = os.path.join(FONTS_DIR, preferred)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    # fallback if Cinzel files are not present
    return load_font("RussoOne-Regular.ttf", size)


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

def center_crop_to_fill(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    w, h = img.size
    src_ratio = w / h
    dst_ratio = target_w / target_h

    if src_ratio > dst_ratio:
        # image too wide
        new_w = int(h * dst_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        # image too tall
        new_h = int(w / dst_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

def draw_tracked_name(base_img, text_value, pos, font, tracking, fill=(236, 236, 240, 255),
                      stroke_fill=(0, 0, 0, 190), stroke_width=3,
                      glow_fill=(255, 220, 170, 46), underline_fill=(255, 200, 90, 0),
                      underline_offset=58, underline_width=2):
    x, y = pos
    chars = list(text_value)
    widths = []
    total_w = 0
    for i, ch in enumerate(chars):
        w = font.getlength(ch)
        widths.append(w)
        total_w += w
        if i < len(chars) - 1:
            total_w += tracking

    
        # soft metallic highlight
        d.text(
            (cx, y - 1),
            ch,
            font=font,
            fill=(255, 255, 255, 28),
        )
        cx += widths[i] + (tracking if i < len(chars) - 1 else 0)

    # subtle gold underline
    ul_y = y + underline_offset
    if underline_width and len(underline_fill) >= 4 and underline_fill[3] > 0:
        d.line((x, ul_y, x + total_w, ul_y), fill=underline_fill, width=underline_width)

    return int(total_w)





def normalize_avatar_input(avatar_img):
    if avatar_img is None:
        return None
    try:
        if isinstance(avatar_img, Image.Image):
            return avatar_img.convert("RGBA")
        if isinstance(avatar_img, (bytes, bytearray)):
            return Image.open(io.BytesIO(avatar_img)).convert("RGBA")
        if isinstance(avatar_img, io.BytesIO):
            avatar_img.seek(0)
            return Image.open(avatar_img).convert("RGBA")
        if isinstance(avatar_img, str):
            if os.path.exists(avatar_img):
                return Image.open(avatar_img).convert("RGBA")
            return None
    except Exception:
        return None
    return None


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
    MUTED: RGBA = (242, 242, 245, 255)
    SUB: RGBA = (170, 173, 184, 255)
    GOLD: RGBA = (255, 214, 96, 255)
    PANEL_FILL: RGBA = (8, 8, 12, 255)
    PANEL_LINE: RGBA = (255, 255, 255, 22)
    STROKE: RGBA = (0, 0, 0, 185)

    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # Top cinematic banner
    banner_h = S(205)
    banner = Image.new("RGBA", (W, banner_h), (6, 6, 10, 255))

    banner_path = os.path.join(ASSETS_DIR, "banner.png")

    if os.path.exists(banner_path):
        try:
            bg = Image.open(banner_path).convert("RGBA")
            banner = center_crop_to_fill(bg, W, banner_h)
        except Exception as e:
            print(f"Banner load error: {e}")

    fade = Image.new("L", (W, banner_h), 0)
    fd = ImageDraw.Draw(fade)
    fd.rectangle((0, 0, W, banner_h), fill=0)
    fade = fade.filter(ImageFilter.GaussianBlur(radius=S(18)))
    fade_rgba = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))
    fade_rgba.putalpha(fade)
    banner = Image.alpha_composite(banner, fade_rgba)

 
    # Side vignettes on banner
    side_vig = Image.new("RGBA", (W, banner_h), (0, 0, 0, 0))
    sv = ImageDraw.Draw(side_vig)
    vig_w = S(180)
    for i in range(vig_w):
        t = 1 - (i / vig_w)
        alpha = int(210 * (t ** 1.6))
        sv.line((i, 0, i, banner_h), fill=(0, 0, 0, alpha))
        sv.line((W - 1 - i, 0, W - 1 - i, banner_h), fill=(0, 0, 0, alpha))

    banner = Image.alpha_composite(banner, side_vig)
    card.paste(banner, (0, 0))
    

    # Main panel
    panel_y = banner_h - S(80)
    panel_x1 = 0
    panel_x2 = W
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

    # Gold divider line under banner
    draw.line((0, panel_y, W, panel_y), fill=(rc[0], rc[1], rc[2], 220), width=S(5))
    draw.line((0, panel_y + S(1), W, panel_y + S(1)), fill=(255, 255, 255, 30), width=S(1))
   

# Square off the top by extending full width - removes rounded top corners
    pd.rectangle((0, panel_y, W, panel_y + S(56)), fill=PANEL_FILL)
    pd.line((0, panel_y, W, panel_y), fill=PANEL_LINE, width=S(2))
    # Square off left and right side edges near top
    pd.rectangle((0, panel_y, S(28), panel_y2), fill=PANEL_FILL)
    pd.rectangle((W - S(28), panel_y, W, panel_y2), fill=PANEL_FILL)
    
    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # Subtle vertical gradient on panel - lighter top fading to nothing for depth
    grad_strip = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(grad_strip)
    for gy in range(panel_y, min(panel_y + S(180), H)):
        t = (gy - panel_y) / S(180)
        alpha = int(20 * (1 - t))
        gd2.line((0, gy, W, gy), fill=(255, 255, 255, alpha))
    card = Image.alpha_composite(card, grad_strip)
    draw = ImageDraw.Draw(card)

    # Avatar block
    av_size = S(174)
    av_x = S(50)
    av_y = panel_y + S(64)

    avatar_img = normalize_avatar_input(avatar_img)
    avatar_has_real_image = avatar_img is not None

    if avatar_has_real_image:
        avatar_img = center_crop_square(avatar_img)
    else:
        avatar_img = Image.new("RGBA", (av_size, av_size), (28, 28, 34, 255))

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

    # paste clean avatar
    card.paste(av_circ, (av_x, av_y), av_circ)

    # outer rank glow
    ring_glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rgd = ImageDraw.Draw(ring_glow)
    rgd.ellipse(
        (av_x - S(8), av_y - S(8), av_x + av_size + S(8), av_y + av_size + S(8)),
        outline=(rc[0], rc[1], rc[2], 55),
        width=S(6),
    )
    ring_glow = ring_glow.filter(ImageFilter.GaussianBlur(radius=S(4)))
    card = Image.alpha_composite(card, ring_glow)
    draw = ImageDraw.Draw(card)

    # main gold ring
    draw.ellipse(
        (av_x - S(2), av_y - S(2), av_x + av_size + S(2), av_y + av_size + S(2)),
        outline=(255, 200, 90, 255),
        width=S(4),
    )

    # inner dark bevel
    draw.ellipse(
        (av_x + S(4), av_y + S(4), av_x + av_size - S(4), av_y + av_size - S(4)),
        outline=(0, 0, 0, 120),
        width=S(2),
    )

    # subtle top ring highlight
    draw.arc(
        (av_x - S(2), av_y - S(2), av_x + av_size + S(2), av_y + av_size + S(2)),
        start=210,
        end=330,
        fill=(255, 235, 170, 80),
        width=S(2),
    )

    # outer rank glow
    ring_glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rgd = ImageDraw.Draw(ring_glow)
    rgd.ellipse(
        (av_x - S(8), av_y - S(8), av_x + av_size + S(8), av_y + av_size + S(8)),
        outline=(rc[0], rc[1], rc[2], 75),
        width=S(6),
    )
    ring_glow = ring_glow.filter(ImageFilter.GaussianBlur(radius=S(4)))
    card = Image.alpha_composite(card, ring_glow)
    draw = ImageDraw.Draw(card)

    # main gold ring
    draw.ellipse(
        (av_x - S(2), av_y - S(2), av_x + av_size + S(2), av_y + av_size + S(2)),
        outline=(255, 200, 90, 255),
        width=S(4),
    )

    # inner dark bevel
    draw.ellipse(
        (av_x + S(4), av_y + S(4), av_x + av_size - S(4), av_y + av_size - S(4)),
        outline=(0, 0, 0, 135),
        width=S(2),
    )

    # subtle top highlight on ring
    draw.arc(
        (av_x - S(2), av_y - S(2), av_x + av_size + S(2), av_y + av_size + S(2)),
        start=210,
        end=330,
        fill=(255, 235, 170, 90),
        width=S(2),
    )

    # Typography / layout anchors
    col_left = panel_x1 + S(28)
    col_right = panel_x2 - S(26)
    name_text = (display_name or "PLAYER").upper()

    f_name = fit_font(draw, name_text, "Cinzel-Bold.ttf", max_w=S(560), start_size=S(58), min_size=S(36))
    f_label = load_font("Inter-VariableFont_opsz,wght.ttf", S(22))
    f_small = load_font("Inter-VariableFont_opsz,wght.ttf", S(15))
    f_value = load_font("Orbitron-VariableFont_wght.ttf", S(30))
    f_big = fit_font(draw, f"{pts} RP", "Orbitron-VariableFont_wght.ttf", max_w=S(420), start_size=S(70), min_size=S(42))

    left_x = col_left + S(20)
    right_x = col_left + int((col_right - col_left) * 0.78)

    top_header_y = panel_y + S(30)
    name_y = top_header_y + S(42)
    name_x = left_x + S(230)

    tracked_name_w = draw_tracked_name(
        card,
        name_text,
        (name_x, name_y - S(5)),
        f_name,
        S(13),
        fill=(248, 248, 252, 255),
        stroke_fill=(8, 8, 12, 175),
        stroke_width=S(2),
        glow_fill=(190, 210, 255, 28),
        underline_fill=(255, 200, 90, 0),
        underline_offset=S(52),
        underline_width=0,
    )
    name_bbox = draw.textbbox((name_x, name_y - S(6)), name_text, font=f_name, stroke_width=S(2))
    badge = get_rank_badge(current_rank_raw, size=S(47))
    if badge:
        badge_y = name_y + (name_bbox[3] - name_bbox[1]) // 2 - badge.size[1] // 2 + 16
        badge_x = min(name_x + tracked_name_w + S(14), right_x - badge.size[0] - S(24))
        card.paste(badge, (badge_x, badge_y), badge)

    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    # Rating nudged down
    rating_label_y = name_y + S(100)
    rating_value_y = rating_label_y + S(34)

    # Record aligned with name (same Y)
    record_label_y = name_y
    record_value_y = record_label_y + S(34)

    # Streak brought upward to tighten the right-side layout
    streak_label_y = rating_label_y + S(2)
    streak_value_y = streak_label_y + S(32)

    # Divider line between name row and rating row - positioned below record value text
    divider_y = name_y + S(88)
    draw.line((name_x, divider_y, right_x + S(160), divider_y), fill=(rc[0], rc[1], rc[2], 35), width=S(2))

    rp_glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rgd = ImageDraw.Draw(rp_glow)
    rgd.rounded_rectangle(
        (name_x - S(18), rating_value_y - S(18), name_x + S(420), rating_value_y + S(94)),
        radius=S(24),
        fill=(rc[0], rc[1], rc[2], 20),
    )
    rgd.text(
        (name_x + S(3), rating_value_y + S(4)),
        f"{pts} RP",
        font=f_big,
        fill=(rc[0], rc[1], rc[2], 110),
        stroke_width=S(2),
        stroke_fill=(0, 0, 0, 0),
    )
    rp_glow = rp_glow.filter(ImageFilter.GaussianBlur(radius=S(14)))
    card = Image.alpha_composite(card, rp_glow)
    draw = ImageDraw.Draw(card)

    draw_tracked(draw, (name_x, rating_label_y), "RATING", f_label, WHITE, S(5), stroke_width=S(1), stroke_fill=(0, 0, 0, 185))

    rp_text = f"{pts} RP"
    rp_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rpd = ImageDraw.Draw(rp_overlay)
    rpd.text((name_x, rating_value_y + S(4)), rp_text, font=f_big, fill=(0, 0, 0, 120))
    rpd.text((name_x, rating_value_y), rp_text, font=f_big, fill=(255, 245, 190, 255))
    rp_alpha = Image.new("L", (W, H), 0)
    rad = ImageDraw.Draw(rp_alpha)
    rad.text((name_x, rating_value_y), rp_text, font=f_big, fill=255)
    gold_grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ggd = ImageDraw.Draw(gold_grad)
    text_h = max(S(72), f_big.size + S(10))
    for i in range(text_h):
        t = i / max(1, text_h - 1)
        r = int(255 * (1 - t) + rc[0] * t)
        g = int(245 * (1 - t) + rc[1] * t)
        b = int(190 * (1 - t) + rc[2] * t)
        ggd.line((name_x - S(4), rating_value_y + i, name_x + S(430), rating_value_y + i), fill=(r, g, b, 255))
    gold_grad.putalpha(rp_alpha)
    card = Image.alpha_composite(card, rp_overlay)
    card = Image.alpha_composite(card, gold_grad)
    draw = ImageDraw.Draw(card)

    draw_tracked(draw, (right_x, record_label_y), "RECORD", f_label, WHITE, S(5), stroke_width=S(1), stroke_fill=(0, 0, 0, 185))
    draw.text((right_x, record_value_y), f"{wins}W – {losses}L", font=f_value, fill=WHITE, stroke_width=S(2), stroke_fill=(0, 0, 0, 155))

    streak_fill = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    streak_text = f"+{streak}" if streak > 0 else str(streak)
    draw_tracked(draw, (right_x, streak_label_y), "STREAK", f_label, WHITE, S(5), stroke_width=S(1), stroke_fill=(0, 0, 0, 185))
    draw.text((right_x, streak_value_y), streak_text, font=f_value, fill=streak_fill, stroke_width=S(2), stroke_fill=(0, 0, 0, 155))

    # Progress/footer strip
    pct_clamped = max(0.0, min(1.0, float(pct)))
    footer_label = "Archive Arena • Season 1"

    badge_slot = S(54)
    bar_w = (col_right - col_left) - badge_slot - S(18)
    bar_h = S(12)
    bar_y = panel_y2 - S(34)
    label_y = bar_y - S(20)

    draw.text((col_left, label_y), footer_label, font=f_small, fill=WHITE, stroke_width=S(1), stroke_fill=(0, 0, 0, 120))
    draw.rounded_rectangle((col_left, bar_y, col_left + bar_w, bar_y + bar_h), radius=S(8), fill=(28, 28, 34, 255))
    fill_w = max(S(14), int(bar_w * pct_clamped)) if pct_clamped > 0 else 0
    if fill_w > 0:
        draw.rounded_rectangle((col_left, bar_y, col_left + fill_w, bar_y + bar_h), radius=S(8), fill=(rc[0], rc[1], rc[2], 255))
        # Shimmer highlight on top edge of filled bar
        draw.line((col_left + S(4), bar_y + S(1), col_left + fill_w - S(4), bar_y + S(1)), fill=(255, 255, 255, 55), width=S(1))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(4))
        if next_badge:
            card.paste(next_badge, (col_left + bar_w + S(18), bar_y + bar_h // 2 - next_badge.size[1] // 2), next_badge)



    # Full gold frame border around the entire card / banner area
    border_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_overlay)

    inset = S(0)

    # Main gold frame only
    bd.rounded_rectangle(
        (inset, inset, W - inset - 1, H - inset - 1),
        radius=S(24),
        outline=(255, 200, 90, 255),
        width=S(2),
    )

    card = Image.alpha_composite(card, border_overlay)
    
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
