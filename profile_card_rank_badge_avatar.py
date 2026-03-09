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


def draw_tracked_name(
    base_img,
    text_value,
    pos,
    font,
    tracking,
    fill=(245, 247, 252, 255),
    stroke_fill=(0, 0, 0, 0),
    stroke_width=0,
    glow_fill=(0, 0, 0, 0),
    underline_fill=(255, 200, 90, 0),
    underline_offset=58,
    underline_width=0,
    gradient_rgb=None,
):
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

    # Tiny shadow keeps the name readable on busy banners/panels.
    for i, ch in enumerate(chars):
        d.text((cx + 1, y + 1), ch, font=font, fill=(0, 0, 0, 70))
        cx += widths[i] + (tracking if i < len(chars) - 1 else 0)

    if gradient_rgb is not None:
        if len(gradient_rgb) >= 3:
            rr, gg, bb = gradient_rgb[:3]
        else:
            rr, gg, bb = (201, 211, 227)

        mask = Image.new("L", base_img.size, 0)
        md = ImageDraw.Draw(mask)
        cx = x
        for i, ch in enumerate(chars):
            md.text(
                (cx, y),
                ch,
                font=font,
                fill=255,
                stroke_width=stroke_width,
                stroke_fill=255 if stroke_width > 0 else 0,
            )
            cx += widths[i] + (tracking if i < len(chars) - 1 else 0)

        grad = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        text_h = max(1, int(font.size * 1.25))
        top_y = max(0, y - 1)
        left_x = max(0, x)
        right_x = min(base_img.size[0], x + int(total_w) + 2)

        top_col = (
            min(255, int(rr + (255 - rr) * 0.78)),
            min(255, int(gg + (255 - gg) * 0.78)),
            min(255, int(bb + (255 - bb) * 0.78)),
        )
        mid_col = (
            min(255, int(rr + (255 - rr) * 0.34)),
            min(255, int(gg + (255 - gg) * 0.34)),
            min(255, int(bb + (255 - bb) * 0.34)),
        )
        bot_col = (
            max(0, int(rr * 0.76)),
            max(0, int(gg * 0.76)),
            max(0, int(bb * 0.82)),
        )

        for i in range(text_h):
            t = i / max(1, text_h - 1)
            if t < 0.42:
                u = t / 0.42
                r = int(top_col[0] * (1 - u) + mid_col[0] * u)
                g = int(top_col[1] * (1 - u) + mid_col[1] * u)
                b = int(top_col[2] * (1 - u) + mid_col[2] * u)
            else:
                u = (t - 0.42) / 0.58
                r = int(mid_col[0] * (1 - u) + bot_col[0] * u)
                g = int(mid_col[1] * (1 - u) + bot_col[1] * u)
                b = int(mid_col[2] * (1 - u) + bot_col[2] * u)
            gd.line((left_x, top_y + i, right_x, top_y + i), fill=(r, g, b, 255))

        # Rim highlight — near-white pass drawn 1px above, masked to letter shapes.
        # Gives letters a lit-from-above feel without banding risk.
        rim = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        rd = ImageDraw.Draw(rim)
        cx2 = x
        for i, ch in enumerate(chars):
            rd.text((cx2, y - 1), ch, font=font, fill=(255, 255, 255, 100))
            cx2 += widths[i] + (tracking if i < len(chars) - 1 else 0)
        rim = rim.filter(ImageFilter.GaussianBlur(radius=0.8))
        base_img.alpha_composite(rim)

        grad.putalpha(mask)
        base_img.alpha_composite(grad)
    else:
        cx = x
        for i, ch in enumerate(chars):
            d.text(
                (cx, y),
                ch,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            cx += widths[i] + (tracking if i < len(chars) - 1 else 0)

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
        img = Image.open(path).convert("RGBA")
        # Strip dark padding only outside the inscribed circle — badge art lives
        # inside the circle, rectangular padding lives in the corners. This avoids
        # zeroing legitimate dark shading within the badge itself.
        pixels = img.load()
        w, h = img.size
        cx, cy, r = w / 2, h / 2, min(w, h) / 2
        threshold = 30
        for py in range(h):
            for px in range(w):
                dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
                if dist > r:  # outside inscribed circle = padding zone only
                    pr, pg, pb, pa = pixels[px, py]
                    if pr < threshold and pg < threshold and pb < threshold:
                        pixels[px, py] = (pr, pg, pb, 0)
        return img.resize((size, size), Image.Resampling.LANCZOS)
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
    Panel base is lifted slightly from pure black so the weave has contrast to work against.
    """
    W, H = base.size
    t = scale_fn(16)  # larger tile = more visible weave structure

    tile = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)

    # Lift cell fill slightly above pure black so weave is visible
    td.rectangle((0, 0, t - 1, t - 1), fill=(255, 255, 255, 12))
    # Hard dark grid lines forming the weave borders
    td.line([(0, 0), (t - 1, 0)], fill=(0, 0, 0, 140), width=1)
    td.line([(0, 0), (0, t - 1)], fill=(0, 0, 0, 140), width=1)
    td.line([(t - 1, 0), (t - 1, t - 1)], fill=(0, 0, 0, 60), width=1)
    td.line([(0, t - 1), (t - 1, t - 1)], fill=(0, 0, 0, 60), width=1)
    # Strong primary specular - top-left facet catching light
    td.line([(0, 0), (t // 2, t // 2)], fill=(255, 255, 255, 90), width=1)
    # Dimmer bottom-right facet
    td.line([(t // 2, t // 2), (t - 1, t - 1)], fill=(255, 255, 255, 28), width=1)
    # Cross-fiber shimmer
    td.line([(0, t // 2), (t // 2, 0)], fill=(255, 255, 255, 25), width=1)
    # Subtle center highlight dot
    mid = t // 2
    td.ellipse((mid - 1, mid - 1, mid + 1, mid + 1), fill=(255, 255, 255, 22))

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
    Metallic divider: blazing bright rank-color in center, fading to transparent at margins.
    """
    W, H = base.size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    mid = (x1 + x2) // 2
    span = x2 - x1

    for px in range(x1, x2):
        dist = abs(px - mid) / (span / 2)
        t = max(0.0, 1.0 - dist ** 1.2)   # slightly less aggressive taper = wider bright zone
        core_alpha = int(255 * t)
        glow_alpha = int(130 * t)
        near_alpha = int(60 * t)

        # Core bright line
        ld.line([(px, y), (px, y + height - 1)],
                fill=(rc[0], rc[1], rc[2], core_alpha), width=1)
        # Wide glow halo above
        ld.line([(px, y - 3), (px, y - 1)],
                fill=(rc[0], rc[1], rc[2], glow_alpha), width=1)
        # Wide glow halo below
        ld.line([(px, y + height), (px, y + height + 3)],
                fill=(rc[0], rc[1], rc[2], glow_alpha), width=1)
        # Outermost soft fringe
        ld.line([(px, y - 5), (px, y - 4)],
                fill=(rc[0], rc[1], rc[2], near_alpha), width=1)
        ld.line([(px, y + height + 4), (px, y + height + 5)],
                fill=(rc[0], rc[1], rc[2], near_alpha), width=1)

    # Stronger blur for cinematic soft glow
    layer = layer.filter(ImageFilter.GaussianBlur(radius=3))
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
                          fill=(8, 12, 26, 175))
    result = Image.alpha_composite(result, glass)

    # Bright top-edge highlight (glass rim light) - stronger
    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.line([(x1, y1), (x2, y1)], fill=(255, 255, 255, 80), width=2)
    rd.line([(x1, y1 + 2), (x2, y1 + 2)], fill=(255, 255, 255, 25), width=1)
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
    LABEL: RGBA = (242, 242, 245, 255)  # solid white labels
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
    # Cleaner seam between banner and main panel
    seam_y = banner_h - S(1)
    draw.line((0, seam_y, W, seam_y), fill=(255, 220, 140, 58), width=S(1))
    draw.line((0, seam_y + S(1), W, seam_y + S(1)), fill=(255, 255, 255, 18), width=S(1))
    draw.line((0, seam_y + S(3), W, seam_y + S(3)), fill=(0, 0, 0, 105), width=S(2))

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
    card = draw_tapered_divider(card, 0, W, panel_y, (255, 200, 90), height=S(4))
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


    mask = soft_circle_mask(av_size, feather=S(2))
    av_circ = Image.new("RGBA", (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, (0, 0), mask=mask)
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Subtle inner shadow so the crop has presence without a tacky halo
    avatar_shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    asd = ImageDraw.Draw(avatar_shadow)
    for inset, alpha in ((S(2), 30), (S(5), 48), (S(8), 28)):
        asd.ellipse(
            (av_x + inset, av_y + inset, av_x + av_size - inset, av_y + av_size - inset),
            outline=(0, 0, 0, alpha),
            width=S(2),
        )
    avatar_shadow = avatar_shadow.filter(ImageFilter.GaussianBlur(radius=S(1)))
    card = Image.alpha_composite(card, avatar_shadow)
    draw = ImageDraw.Draw(card)

    # Main gold ring
    outer_ring = (av_x - S(3), av_y - S(3), av_x + av_size + S(3), av_y + av_size + S(3))
    draw.ellipse(outer_ring, outline=(255, 200, 90, 255), width=S(5))
    # Clean inner dark bevel
    draw.ellipse(
        (av_x + S(4), av_y + S(4), av_x + av_size - S(4), av_y + av_size - S(4)),
        outline=(0, 0, 0, 150), width=S(2),
    )
    # Fine bright inner rim for a cleaner premium finish
    draw.ellipse(
        (av_x + S(1), av_y + S(1), av_x + av_size - S(1), av_y + av_size - S(1)),
        outline=(255, 245, 190, 72), width=S(1),
    )
    # Specular arc highlight on top-left of ring
    draw.arc(outer_ring, start=205, end=320, fill=(255, 248, 205, 125), width=S(2))
    # Subtle lower shadow arc so the ring feels seated
    draw.arc(outer_ring, start=30, end=145, fill=(0, 0, 0, 72), width=S(2))

    # -------------------------------------------------------
    # Typography / layout anchors
    # -------------------------------------------------------
    col_left = panel_x1 + S(28)
    col_right = panel_x2 - S(26)
    name_text = (display_name or "PLAYER").upper()

    left_x = col_left + S(20)
    right_x = col_left + int((col_right - col_left) * 0.78)
    top_header_y = panel_y + S(30)
    name_y = top_header_y + S(42)
    name_x = left_x + S(230)

    # Name must not bleed into the right stats column — hard cap at right_x with margin.
    # The rank badge now lives on the avatar corner, so the full name row can use that freed space.
    name_tracking = S(8)
    name_max_w = right_x - name_x - S(40)

    def name_rendered_w(text, font):
        """Width including inter-character tracking."""
        return text_width(draw, text, font) + name_tracking * (len(text) - 1)

    # Shrink font until tracked width fits
    f_name_size = S(64)
    f_name = load_cinzel_font(f_name_size)
    while f_name_size > S(26) and name_rendered_w(name_text, f_name) > name_max_w:
        f_name_size -= 1
        f_name = load_cinzel_font(f_name_size)

    # If even min size still overflows, truncate character by character
    if name_rendered_w(name_text, f_name) > name_max_w:
        t = name_text
        while len(t) > 1 and name_rendered_w(t + "…", f_name) > name_max_w:
            t = t[:-1]
        name_text = t + "…"
    f_label = load_font("Inter-VariableFont_opsz,wght.ttf", S(22))
    f_small = load_font("Inter-VariableFont_opsz,wght.ttf", S(15))
    f_value = load_font("Orbitron-VariableFont_wght.ttf", S(30))
    # f_big sized for the NUMBER only, f_rp is ~55% for the "RP" suffix
    f_big = fit_font(draw, f"{pts}", "Orbitron-VariableFont_wght.ttf", max_w=S(340), start_size=S(70), min_size=S(42))
    f_rp = load_font("Orbitron-VariableFont_wght.ttf", int(f_big.size * 0.55))

    # Tiered fallback: prestige ranks (Diamond, Platinum, Gold) keep their rank color
    # in the name gradient. Silver and Bronze fall back to card gold so they still look premium.
    CARD_GOLD = (255, 200, 90)
    _rank_clean = clean_rank_name(current_rank_raw).upper()
    name_gradient_rgb = rc if _rank_clean in ("DIAMOND", "PLATINUM", "GOLD", "SILVER") else CARD_GOLD

    tracked_name_w = draw_tracked_name(
      card, name_text, (name_x, name_y - S(5)), f_name, name_tracking,
      fill=(245, 247, 252, 255),
      stroke_fill=(0, 0, 0, 0),
      stroke_width=0,
      glow_fill=(190, 210, 255, 10),
      underline_fill=(255, 200, 90, 0),
      underline_offset=S(52),
      underline_width=0,
      gradient_rgb=name_gradient_rgb,
    )

    name_draw_y = name_y - S(5)  # actual Y the text is drawn at
    badge = get_rank_badge(current_rank_raw, size=S(68))
    if badge:
        # Discord-style indicator: badge corner overlaps avatar ring, shifted left so it
        # sits against the ring rather than floating below-right.
        badge_x = av_x + av_size - S(48)
        badge_y = av_y + av_size - S(48)

        card.paste(badge, (badge_x, badge_y), badge)

    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    rating_label_y = name_y + S(100)
    rating_value_y = rating_label_y + S(34)
    record_label_y = name_y
    record_value_y = record_label_y + S(34)
    streak_label_y = rating_label_y + S(2)
    streak_value_y = streak_label_y + S(42)

    # Divider between name row and rating row
    divider_y = name_y + S(88)
    draw.line((name_x, divider_y, right_x + S(160), divider_y),
              fill=(255, 200, 90, 70), width=S(3))

    # RP holographic gold glow background
    num_text = f"{pts}"
    num_w = text_width(draw, num_text, f_big)
    rp_x = name_x + num_w + S(4)
    # RP baseline aligned to bottom of number
    num_bbox = draw.textbbox((name_x, rating_value_y), num_text, font=f_big)
    rp_y = num_bbox[3] - draw.textbbox((0, 0), "RP", font=f_rp)[3] - S(2)

    draw_tracked(draw, (name_x, rating_label_y), "RATING", f_label, LABEL, S(5),
                 stroke_width=S(1), stroke_fill=(0, 0, 0, 185))

    # Number - full gold holographic gradient
    rp_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rpd = ImageDraw.Draw(rp_overlay)
    rpd.text((name_x, rating_value_y + S(4)), num_text, font=f_big, fill=(0, 0, 0, 120))
    rpd.text((name_x, rating_value_y), num_text, font=f_big, fill=(255, 245, 190, 255))
    # "RP" suffix - same gradient but rendered at smaller size, bottom-aligned
    rpd.text((rp_x, rp_y + S(4)), "RP", font=f_rp, fill=(0, 0, 0, 100))
    rpd.text((rp_x, rp_y), "RP", font=f_rp, fill=(255, 245, 190, 255))

    rp_alpha = Image.new("L", (W, H), 0)
    rad = ImageDraw.Draw(rp_alpha)
    rad.text((name_x, rating_value_y), num_text, font=f_big, fill=255)
    rad.text((rp_x, rp_y), "RP", font=f_rp, fill=255)

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

    draw_tracked(draw, (right_x, record_label_y), "RECORD", f_label, LABEL, S(5),
                 stroke_width=S(1), stroke_fill=(0, 0, 0, 185))
    draw.text((right_x, record_value_y), f"{wins}W \u2013 {losses}L",
              font=f_value, fill=WHITE, stroke_width=S(2), stroke_fill=(0, 0, 0, 155))

    streak_fill = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    streak_text = f"+{streak}" if streak > 0 else str(streak)
    draw_tracked(draw, (right_x, streak_label_y), "STREAK", f_label, LABEL, S(5),
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
    footer_glass_y = label_y - S(10)
    card = apply_glassmorphism_footer(
        card, panel_x1, footer_glass_y, panel_x2, panel_y2, radius=S(14)
    )
    draw = ImageDraw.Draw(card)

    # Cleaner metallic separator so the footer feels integrated, not leftover
    draw.line((0, footer_glass_y, W, footer_glass_y), fill=(255, 255, 255, 30), width=S(1))
    draw.line((0, footer_glass_y + S(2), W, footer_glass_y + S(2)), fill=(0, 0, 0, 76), width=S(1))

    draw.text((col_left, label_y), footer_label, font=f_small, fill=(252, 252, 255, 242),
              stroke_width=S(1), stroke_fill=(0, 0, 0, 120))

    # Slimmer, more intentional progress trough
    bar_top = bar_y + S(1)
    bar_bottom = bar_y + bar_h - S(1)
    draw.rounded_rectangle((col_left, bar_top, col_left + bar_w, bar_bottom),
                            radius=S(8), fill=(16, 18, 26, 228), outline=(255, 255, 255, 22), width=S(1))
    draw.line((col_left + S(6), bar_top + S(1), col_left + bar_w - S(6), bar_top + S(1)),
              fill=(255, 255, 255, 28), width=S(1))
    draw.line((col_left + S(6), bar_bottom - S(1), col_left + bar_w - S(6), bar_bottom - S(1)),
              fill=(0, 0, 0, 58), width=S(1))

    fill_w = max(S(14), int(bar_w * pct_clamped)) if pct_clamped > 0 else 0
    if fill_w > 0:
        draw.rounded_rectangle((col_left, bar_top, col_left + fill_w, bar_bottom),
                                radius=S(8), fill=(rc[0], rc[1], rc[2], 245))
        draw.line((col_left + S(5), bar_top + S(1), col_left + fill_w - S(5), bar_top + S(1)),
                  fill=(255, 255, 255, 88), width=S(1))
        draw.line((col_left + S(5), bar_bottom - S(1), col_left + fill_w - S(5), bar_bottom - S(1)),
                  fill=(0, 0, 0, 52), width=S(1))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(4))
        if next_badge:
            anchor_x = col_left + bar_w + S(18)
            anchor_y = bar_y + bar_h // 2 - next_badge.size[1] // 2
            # Integrated footer anchor instead of a bolted-on black button
            draw.rounded_rectangle(
                (anchor_x - S(10), anchor_y - S(8), anchor_x + next_badge.size[0] + S(10), anchor_y + next_badge.size[1] + S(8)),
                radius=S(14), fill=(8, 10, 18, 118), outline=(255, 255, 255, 16), width=S(1),
            )
            draw.arc(
                (anchor_x - S(10), anchor_y - S(8), anchor_x + next_badge.size[0] + S(10), anchor_y + next_badge.size[1] + S(8)),
                start=200, end=340, fill=(255, 245, 190, 36), width=S(1)
            )
            card.paste(next_badge, (anchor_x, anchor_y), next_badge)

    # -------------------------------------------------------
    # Gold frame border + inner shadow
    # -------------------------------------------------------
    border_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_overlay)
    bd.rounded_rectangle(
        (0, 0, W - 1, H - 1), radius=S(24),
        outline=(255, 200, 90, 255), width=S(2),
    )
    # Inner shadow - faint dark ring just inside the border for depth
    bd.rounded_rectangle(
        (S(3), S(3), W - S(4), H - S(4)), radius=S(22),
        outline=(0, 0, 0, 80), width=S(3),
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
