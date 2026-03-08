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


def fit_font(draw, text, preferred_filename, max_w, start_size, min_size):
    size = start_size
    while size >= min_size:
        f = load_font(preferred_filename, size)
        if text_width(draw, text, f) <= max_w:
            return f
        size -= 1
    return load_font(preferred_filename, min_size)


def draw_tracked(draw, xy, text, font, fill, tracking, *, stroke_width=0, stroke_fill=None):
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
def center_crop_square(img):
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def center_crop_to_fill(img, target_w, target_h):
    w, h = img.size
    src_ratio = w / h
    dst_ratio = target_w / target_h
    if src_ratio > dst_ratio:
        new_w = int(h * dst_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / dst_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)


def draw_tracked_name(base_img, text_value, pos, font, tracking,
                      fill=(236, 236, 240, 255),
                      stroke_fill=(56, 62, 76, 120), stroke_width=2,
                      glow_fill=(225, 235, 255, 54), underline_fill=(255, 200, 90, 0),
                      underline_offset=58, underline_width=2):
    """
    Renders username with a brighter brushed-silver metallic sheen:
    - Soft cool glow for separation
    - Reduced dark shadowing so the silver reads clean
    - Bright upper-edge specular pass
    - Subtle shimmer pass for polished metal depth
    """
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

    d = ImageDraw.Draw(base_img)
    cx = x

    # Soft overall glow behind the word so it pops from the panel
    if len(glow_fill) >= 4 and glow_fill[3] > 0:
        glow_offsets = [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1)]
        for ox, oy in glow_offsets:
            gx = x
            for i, ch in enumerate(chars):
                d.text((gx + ox, y + oy), ch, font=font, fill=glow_fill)
                gx += widths[i] + (tracking if i < len(chars) - 1 else 0)

    for i, ch in enumerate(chars):
        # Softer depth shadow - enough lift without dirtying the silver
        d.text((cx + 2, y + 2), ch, font=font, fill=(0, 0, 0, 70))
        d.text((cx + 1, y + 1), ch, font=font, fill=(20, 24, 32, 38))
        # Main metallic body
        d.text((cx, y), ch, font=font,
               fill=fill,
               stroke_width=stroke_width,
               stroke_fill=stroke_fill)
        # Bright top-edge sheen
        d.text((cx, y - 1), ch, font=font, fill=(255, 255, 255, 168))
        # Extra polished highlight slightly left/up
        d.text((cx - 1, y - 1), ch, font=font, fill=(245, 248, 255, 72))
        # Cool silver shimmer to keep the metal look crisp
        d.text((cx - 1, y), ch, font=font, fill=(210, 220, 240, 34))
        cx += widths[i] + (tracking if i < len(chars) - 1 else 0)

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


def soft_circle_mask(size, feather=4):
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
def apply_anime_arena_background(base, art, *, focus_right=True, art_strength=0.9,
                                  blur_px=7, saturation=1.12, brightness=0.78,
                                  contrast=1.1, tint=(110, 70, 180, 18)):
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
# Carbon fiber hex weave
# ----------------------------
def apply_carbon_fiber(base: Image.Image, p_x1: int, p_y1: int, p_x2: int, p_y2: int,
                        radius: int, scale_fn) -> Image.Image:
    """
    Dark-on-dark hexagonal weave with specular highlights on cell edges.
    Uses a diamond/rhombus tile arrangement that reads as hex weave at scale.
    """
    W, H = base.size
    t = scale_fn(12)  # tile size

    tile = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)

    # Very dark cell fill - barely lighter than panel background
    td.rectangle((0, 0, t - 1, t - 1), fill=(255, 255, 255, 5))
    # Dark grid lines - the "weave" structure
    td.line([(0, 0), (t - 1, 0)], fill=(0, 0, 0, 100), width=1)
    td.line([(0, 0), (0, t - 1)], fill=(0, 0, 0, 100), width=1)
    # Primary specular highlight - bright edge catching light (top-left facet)
    td.line([(0, 0), (t // 2, t // 2)], fill=(255, 255, 255, 65), width=1)
    # Secondary specular - dimmer bottom-right facet
    td.line([(t // 2, t // 2), (t - 1, t - 1)], fill=(255, 255, 255, 20), width=1)
    # Cross-fiber highlight - horizontal mid-point shimmer
    td.line([(0, t // 2), (t // 2, 0)], fill=(255, 255, 255, 18), width=1)

    pattern_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for py in range(p_y1, p_y2, t):
        offset = (t // 2) if ((py // t) % 2) == 1 else 0
        for px in range(p_x1 - t, p_x2, t):
            pattern_layer.paste(tile, (px + offset, py))

    # Clip to rounded panel bounds
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((p_x1, p_y1, p_x2, p_y2), radius=radius, fill=255)
    masked = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    masked.paste(pattern_layer, mask=mask)
    return Image.alpha_composite(base, masked)


# ----------------------------
# Tapered metallic divider
# ----------------------------
def draw_tapered_divider(base: Image.Image, x1: int, x2: int, y: int,
                          rc: tuple, height: int = 4) -> Image.Image:
    """
    Metallic divider line: bright rank-colored glow in the center,
    fading to transparent at both margins. Drawn on a separate layer
    and blurred for a soft-light effect.
    """
    W, H = base.size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    mid = (x1 + x2) // 2
    span = x2 - x1

    # Draw horizontal line with alpha gradient from center out
    for px in range(x1, x2):
        dist = abs(px - mid) / (span / 2)          # 0 at center, 1 at edge
        t = max(0.0, 1.0 - dist ** 1.4)            # smooth taper
        core_alpha = int(240 * t)
        glow_alpha = int(90 * t)

        # Core bright line
        ld.line([(px, y), (px, y + height - 1)],
                fill=(rc[0], rc[1], rc[2], core_alpha), width=1)
        # Soft glow halo above and below
        ld.line([(px, y - 2), (px, y - 1)],
                fill=(rc[0], rc[1], rc[2], glow_alpha), width=1)
        ld.line([(px, y + height), (px, y + height + 2)],
                fill=(rc[0], rc[1], rc[2], glow_alpha), width=1)

    # Blur for soft cinematic glow
    layer = layer.filter(ImageFilter.GaussianBlur(radius=2))
    return Image.alpha_composite(base, layer)


# ----------------------------
# Glassmorphism footer
# ----------------------------
def apply_glassmorphism_footer(base: Image.Image, x1: int, y1: int, x2: int, y2: int,
                                radius: int) -> Image.Image:
    """
    Frosted-glass footer: blurs the region beneath it, overlays a
    semi-transparent tinted panel, and adds a bright top-edge highlight.
    """
    W, H = base.size

    # Crop the region, blur it to simulate frosted glass
    region = base.crop((x1, y1, x2, y2))
    blurred = region.filter(ImageFilter.GaussianBlur(radius=8))

    # Paste blurred region back
    result = base.copy()
    blur_mask = Image.new("L", blurred.size, 255)
    result.paste(blurred, (x1, y1), mask=blur_mask)

    # Semi-transparent dark tint overlay with slight blue hue (glass tint)
    glass = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle((x1, y1, x2, y2), radius=radius,
                          fill=(10, 14, 28, 140))
    result = Image.alpha_composite(result, glass)

    # Bright top-edge highlight (glass rim light)
    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.line([(x1 + radius, y1), (x2 - radius, y1)],
            fill=(255, 255, 255, 60), width=1)
    result = Image.alpha_composite(result, rim)

    return result


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
    PANEL_FILL: RGBA = (8, 8, 12, 255)
    PANEL_LINE: RGBA = (255, 255, 255, 22)

    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # -------------------------------------------------------
    # Top cinematic banner with depth-of-field edge vignette
    # -------------------------------------------------------
    banner_h = S(205)
    banner = Image.new("RGBA", (W, banner_h), (6, 6, 10, 255))

    banner_path = os.path.join(ASSETS_DIR, "banner.png")
    if os.path.exists(banner_path):
        try:
            bg = Image.open(banner_path).convert("RGBA")
            banner = center_crop_to_fill(bg, W, banner_h)
        except Exception as e:
            print(f"Banner load error: {e}")

    # Bottom fade into panel
    fade = Image.new("L", (W, banner_h), 0)
    fd = ImageDraw.Draw(fade)
    fd.rectangle((0, 0, W, banner_h), fill=0)
    fade = fade.filter(ImageFilter.GaussianBlur(radius=S(18)))
    fade_rgba = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))
    fade_rgba.putalpha(fade)
    banner = Image.alpha_composite(banner, fade_rgba)

    # Depth-of-field side vignettes - stronger blur toward edges
    side_vig = Image.new("RGBA", (W, banner_h), (0, 0, 0, 0))
    sv = ImageDraw.Draw(side_vig)
    vig_w = S(220)
    for i in range(vig_w):
        t = 1 - (i / vig_w)
        alpha = int(230 * (t ** 1.8))
        sv.line((i, 0, i, banner_h), fill=(0, 0, 0, alpha))
        sv.line((W - 1 - i, 0, W - 1 - i, banner_h), fill=(0, 0, 0, alpha))
    banner = Image.alpha_composite(banner, side_vig)
    card.paste(banner, (0, 0))

    # -------------------------------------------------------
    # Main panel
    # -------------------------------------------------------
    panel_y = banner_h - S(80)
    panel_x1 = 0
    panel_x2 = W
    panel_y2 = H - S(24)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle(
        (panel_x1, panel_y, panel_x2, panel_y2),
        radius=S(28), fill=PANEL_FILL, outline=PANEL_LINE, width=S(2),
    )
    # Square off top corners and side edges
    pd.rectangle((0, panel_y, W, panel_y + S(56)), fill=PANEL_FILL)
    pd.line((0, panel_y, W, panel_y), fill=PANEL_LINE, width=S(2))
    pd.rectangle((0, panel_y, S(28), panel_y2), fill=PANEL_FILL)
    pd.rectangle((W - S(28), panel_y, W, panel_y2), fill=PANEL_FILL)

    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # -------------------------------------------------------
    # Carbon fiber hex weave texture over panel
    # -------------------------------------------------------
    card = apply_carbon_fiber(card, panel_x1, panel_y, panel_x2, panel_y2,
                               radius=S(28), scale_fn=S)
    draw = ImageDraw.Draw(card)

    # -------------------------------------------------------
    # Tapered metallic divider (replaces flat gold line)
    # -------------------------------------------------------
    card = draw_tapered_divider(card, 0, W, panel_y, rc, height=S(4))
    draw = ImageDraw.Draw(card)
    # Subtle white shimmer line on top edge
    draw.line((0, panel_y + S(1), W, panel_y + S(1)), fill=(255, 255, 255, 25), width=S(1))

    # Subtle vertical gradient on panel for depth
    grad_strip = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(grad_strip)
    for gy in range(panel_y, min(panel_y + S(180), H)):
        t = (gy - panel_y) / S(180)
        alpha = int(18 * (1 - t))
        gd2.line((0, gy, W, gy), fill=(255, 255, 255, alpha))
    card = Image.alpha_composite(card, grad_strip)
    draw = ImageDraw.Draw(card)

    # -------------------------------------------------------
    # Avatar block
    # -------------------------------------------------------
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

    # Rank-colored ambient glow behind avatar
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = av_x + av_size // 2
    cy = av_y + av_size // 2
    for r in range(S(220), 0, -S(10)):
        a = int(55 * (1 - r / S(220)) ** 2)
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(rc[0], rc[1], rc[2], a))
    card = Image.alpha_composite(card, glow)
    draw = ImageDraw.Draw(card)

    mask = soft_circle_mask(av_size, feather=S(2))
    av_circ = Image.new("RGBA", (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, (0, 0), mask=mask)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Rim-light: strong rank-color halo around avatar (prestige effect)
    rim_light = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rl = ImageDraw.Draw(rim_light)
    # Outer wide soft rim
    for offset in range(S(14), 0, -S(2)):
        a = int(80 * (1 - offset / S(14)))
        rl.ellipse(
            (av_x - offset, av_y - offset,
             av_x + av_size + offset, av_y + av_size + offset),
            outline=(rc[0], rc[1], rc[2], a), width=S(2),
        )
    rim_light = rim_light.filter(ImageFilter.GaussianBlur(radius=S(5)))
    card = Image.alpha_composite(card, rim_light)
    draw = ImageDraw.Draw(card)

    # Main gold ring
    draw.ellipse(
        (av_x - S(2), av_y - S(2), av_x + av_size + S(2), av_y + av_size + S(2)),
        outline=(255, 200, 90, 255), width=S(4),
    )
    # Inner dark bevel
    draw.ellipse(
        (av_x + S(4), av_y + S(4), av_x + av_size - S(4), av_y + av_size - S(4)),
        outline=(0, 0, 0, 135), width=S(2),
    )
    # Specular arc highlight on top of ring
    draw.arc(
        (av_x - S(2), av_y - S(2), av_x + av_size + S(2), av_y + av_size + S(2)),
        start=210, end=330, fill=(255, 245, 190, 100), width=S(2),
    )

    # -------------------------------------------------------
    # Typography / layout anchors
    # -------------------------------------------------------
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

    # Username - brushed silver metallic with increased tracking
    tracked_name_w = draw_tracked_name(
        card, name_text, (name_x, name_y - S(5)), f_name, S(13),
        fill=(228, 232, 240, 255),
        stroke_fill=(56, 62, 76, 120),
        stroke_width=S(2),
        glow_fill=(220, 232, 255, 54),
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

    rating_label_y = name_y + S(100)
    rating_value_y = rating_label_y + S(34)
    record_label_y = name_y
    record_value_y = record_label_y + S(34)
    streak_label_y = rating_label_y + S(2)
    streak_value_y = streak_label_y + S(32)

    # Divider between name row and rating row
    divider_y = name_y + S(88)
    draw.line((name_x, divider_y, right_x + S(160), divider_y),
              fill=(rc[0], rc[1], rc[2], 35), width=S(2))

    # RP holographic gold glow background
    rp_glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rgd = ImageDraw.Draw(rp_glow)
    rgd.rounded_rectangle(
        (name_x - S(18), rating_value_y - S(18), name_x + S(420), rating_value_y + S(94)),
        radius=S(24), fill=(rc[0], rc[1], rc[2], 20),
    )
    rgd.text(
        (name_x + S(3), rating_value_y + S(4)), f"{pts} RP", font=f_big,
        fill=(rc[0], rc[1], rc[2], 120), stroke_width=S(2), stroke_fill=(0, 0, 0, 0),
    )
    rp_glow = rp_glow.filter(ImageFilter.GaussianBlur(radius=S(16)))
    card = Image.alpha_composite(card, rp_glow)
    draw = ImageDraw.Draw(card)

    draw_tracked(draw, (name_x, rating_label_y), "RATING", f_label, WHITE, S(5),
                 stroke_width=S(1), stroke_fill=(0, 0, 0, 185))

    # RP value - gold holographic gradient
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
        ggd.line((name_x - S(4), rating_value_y + i, name_x + S(430), rating_value_y + i),
                 fill=(r, g, b, 255))
    gold_grad.putalpha(rp_alpha)
    card = Image.alpha_composite(card, rp_overlay)
    card = Image.alpha_composite(card, gold_grad)
    draw = ImageDraw.Draw(card)

    draw_tracked(draw, (right_x, record_label_y), "RECORD", f_label, WHITE, S(5),
                 stroke_width=S(1), stroke_fill=(0, 0, 0, 185))
    draw.text((right_x, record_value_y), f"{wins}W \u2013 {losses}L",
              font=f_value, fill=WHITE, stroke_width=S(2), stroke_fill=(0, 0, 0, 155))

    streak_fill = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    streak_text = f"+{streak}" if streak > 0 else str(streak)
    draw_tracked(draw, (right_x, streak_label_y), "STREAK", f_label, WHITE, S(5),
                 stroke_width=S(1), stroke_fill=(0, 0, 0, 185))
    draw.text((right_x, streak_value_y), streak_text,
              font=f_value, fill=streak_fill, stroke_width=S(2), stroke_fill=(0, 0, 0, 155))

    # -------------------------------------------------------
    # Glassmorphism footer strip
    # -------------------------------------------------------
    pct_clamped = max(0.0, min(1.0, float(pct)))
    footer_label = "Archive Arena \u2022 Season 1"

    badge_slot = S(54)
    bar_w = (col_right - col_left) - badge_slot - S(18)
    bar_h = S(12)
    bar_y = panel_y2 - S(34)
    label_y = bar_y - S(20)

    # Frosted glass region behind footer text and bar
    footer_glass_y = label_y - S(8)
    card = apply_glassmorphism_footer(
        card, panel_x1, footer_glass_y, panel_x2, panel_y2, radius=S(14)
    )
    draw = ImageDraw.Draw(card)

    draw.text((col_left, label_y), footer_label, font=f_small, fill=WHITE,
              stroke_width=S(1), stroke_fill=(0, 0, 0, 120))
    draw.rounded_rectangle((col_left, bar_y, col_left + bar_w, bar_y + bar_h),
                            radius=S(8), fill=(28, 28, 34, 200))
    fill_w = max(S(14), int(bar_w * pct_clamped)) if pct_clamped > 0 else 0
    if fill_w > 0:
        draw.rounded_rectangle((col_left, bar_y, col_left + fill_w, bar_y + bar_h),
                                radius=S(8), fill=(rc[0], rc[1], rc[2], 255))
        draw.line((col_left + S(4), bar_y + S(1), col_left + fill_w - S(4), bar_y + S(1)),
                  fill=(255, 255, 255, 65), width=S(1))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(4))
        if next_badge:
            card.paste(next_badge,
                       (col_left + bar_w + S(18), bar_y + bar_h // 2 - next_badge.size[1] // 2),
                       next_badge)

    # -------------------------------------------------------
    # Gold frame border
    # -------------------------------------------------------
    border_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_overlay)
    bd.rounded_rectangle(
        (0, 0, W - 1, H - 1), radius=S(24),
        outline=(255, 200, 90, 255), width=S(2),
    )
    card = Image.alpha_composite(card, border_overlay)

    # Bottom edge vignette
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
