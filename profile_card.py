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
FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

# ----------------------------
# Anime arena background overlay
# ----------------------------
def apply_anime_arena_background(
    base: Image.Image,
    art: Image.Image,
    *,
    focus_right: bool = True,
    art_strength: float = 0.75,   # stronger so you actually see it
    blur_px: int = 6,             # less blur = more “anime vibe”
    saturation: float = 1.15,     # keep anime pop
    brightness: float = 0.75,     # less dark so color shows
    contrast: float = 1.05,
    left_protect_width: float = 0.45,  # protect UI area but not too aggressive
    left_protect_alpha: int = 140,     # lower than 200 so art still shows
) -> Image.Image:
    """
    Anime-style background plate:
    - cover-fit art (optional right-bias crop)
    - blur/contrast/brightness/saturation controls
    - left readability gradient (subtle)
    - vignette + bloom
    """
    W, H = base.size
    art = art.convert("RGBA")

    # --- Cover-fit with optional right bias
    aw, ah = art.size
    target_ratio = W / H
    art_ratio = aw / ah

    if art_ratio > target_ratio:
        # too wide -> crop width
        new_w = int(ah * target_ratio)
        left = aw - new_w if focus_right else (aw - new_w) // 2
        art = art.crop((left, 0, left + new_w, ah))
    else:
        # too tall -> crop height
        new_h = int(aw / target_ratio)
        top = (ah - new_h) // 2
        art = art.crop((0, top, aw, top + new_h))

    art = art.resize((W, H), Image.Resampling.LANCZOS)

    # --- Make it background-friendly
    if blur_px > 0:
        art = art.filter(ImageFilter.GaussianBlur(radius=blur_px))

    art = ImageEnhance.Color(art).enhance(saturation)
    art = ImageEnhance.Contrast(art).enhance(contrast)
    art = ImageEnhance.Brightness(art).enhance(brightness)

    # --- Apply art with controlled opacity
    a = art.split()[-1].point(lambda v: int(v * art_strength))
    art.putalpha(a)
    out = Image.alpha_composite(base, art)

    # --- Subtle magic tint to lean “arena / sorcerer” without clutter
    tint = Image.new("RGBA", (W, H), (120, 60, 180, 28))  # soft purple glow
    out = Image.alpha_composite(out, tint)

    # --- Left readability gradient (protects text/UI)
    grad = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(grad)
    gd.rectangle((0, 0, int(W * left_protect_width), H), fill=left_protect_alpha)
    grad = grad.filter(ImageFilter.GaussianBlur(radius=int(W * 0.08)))

    shade = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    shade.putalpha(grad)
    out = Image.alpha_composite(out, shade)

    # --- Subtle vignette
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    pad = int(min(W, H) * 0.10)
    vd.ellipse((pad, pad, W - pad, H - pad), fill=180)
    vig = vig.filter(ImageFilter.GaussianBlur(radius=int(min(W, H) * 0.12)))

    edge_dark = Image.new("RGBA", (W, H), (0, 0, 0, 210))
    edge_dark.putalpha(ImageChops.invert(vig))
    out = Image.alpha_composite(out, edge_dark)

    # --- Soft bloom (keeps “magic glow” vibe)
    bright_pass = ImageEnhance.Brightness(out).enhance(1.18).filter(ImageFilter.GaussianBlur(radius=6))
    out = ImageChops.screen(out, bright_pass)

    return out

# ----------------------------
# Font loading (cached)
# ----------------------------
@lru_cache(maxsize=128)
def load_font(preferred_filename: str, size: int) -> ImageFont.FreeTypeFont:
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

def fit_font(draw: ImageDraw.ImageDraw, text: str, preferred_filename: str, max_w: int, start_size: int, min_size: int) -> ImageFont.ImageFont:
    """Return a font that shrinks until text fits max_w."""
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
    """Creates a slightly feathered circle mask."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((feather, feather, size - feather - 1, size - feather - 1), fill=255)
    m2 = m.resize((size * 2, size * 2), Image.Resampling.BICUBIC).resize((size, size), Image.Resampling.LANCZOS)
    return m2

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
# Rank badge utils
# ----------------------------
def clean_rank_name(name: str) -> str:
    return re.sub(r"<:[^:]+:\d+>\s*", "", name).strip()

BADGES_DIR = os.path.join(os.path.dirname(__file__), "badges")
RANK_BADGES = {
    "DIAMOND":  os.path.join(BADGES_DIR, "rank_diamond.png"),
    "PLATINUM": os.path.join(BADGES_DIR, "rank_platinum.png"),
    "GOLD":     os.path.join(BADGES_DIR, "rank_gold.png"),
    "SILVER":   os.path.join(BADGES_DIR, "rank_silver.png"),
    "BRONZE":   os.path.join(BADGES_DIR, "rank_bronze.png"),
}

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
# Main card generator (crisp)
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
    W, H = 900 * SCALE, 460 * SCALE
    rc = rank_color

    def S(x: int) -> int:
        return x * SCALE

    # Base
    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # ✅ Apply anime arena background FIRST (so your UI draws on top)
    bg_path = os.path.join(ASSETS_DIR, "arena_bg.png")
    bg_loaded = False
    if os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert("RGBA")
            card = apply_anime_arena_background(
                card,
                bg,
                focus_right=True,
                # defaults are already stronger in the function signature,
                # but you can override here if you want:
                art_strength=0.78,
                blur_px=6,
                saturation=1.15,
                brightness=0.75,
                contrast=1.05,
                left_protect_width=0.45,
                left_protect_alpha=140,
            )
            bg_loaded = True
        except Exception as e:
            print(f"Background overlay error: {e}")

    draw = ImageDraw.Draw(card)

    # Optional: ultra-light dark wash for contrast (won't kill the art)
    card = Image.alpha_composite(card, Image.new("RGBA", (W, H), (0, 0, 0, 20)))
    draw = ImageDraw.Draw(card)

    # Colors
    WHITE: RGBA = (238, 236, 232, 255)
    MUTED: RGBA = (155, 155, 165, 255)
    DIM: RGBA   = (40, 40, 48, 255)

    # Avatar placement
    av_size = S(220)
    av_x = S(40)
    av_y = (H - av_size) // 2 - S(20)

    if avatar_img is None:
        avatar_img = Image.new("RGBA", (av_size, av_size), (25, 25, 28, 255))
    else:
        avatar_img = center_crop_square(avatar_img.convert("RGBA"))

    av = avatar_img.resize((av_size, av_size), Image.Resampling.LANCZOS)

    # Glow behind avatar (tight & clean)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx = av_x + av_size // 2
    gy = av_y + av_size // 2
    for r in range(S(170), 0, -S(10)):
        a = int(40 * (1 - r / S(170)) ** 2)
        gd.ellipse((gx - r, gy - r, gx + r, gy + r), fill=(rc[0], rc[1], rc[2], a))
    card = Image.alpha_composite(card, glow)
    draw = ImageDraw.Draw(card)

    # Avatar circle
    mask = soft_circle_mask(av_size, feather=S(2))
    av_circ = Image.new("RGBA", (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, (0, 0), mask=mask)

    # Clean ring
    ring_rect = (av_x - S(6), av_y - S(6), av_x + av_size + S(6), av_y + av_size + S(6))
    draw.ellipse(ring_rect, outline=(rc[0], rc[1], rc[2], 210), width=S(4))
    card.paste(av_circ, (av_x, av_y), av_circ)

    # Badge overlap
    badge_size = S(72)
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        bx = av_x + av_size - S(54)
        by = av_y + av_size - S(54)
        card.paste(cur_badge, (bx, by), cur_badge)

    # Column anchors
    col_name = S(295)
    col_stats = S(660)
    right_pad = S(30)

    # Fonts (fit-to-width)
    name_text = (display_name or "PLAYER").upper()
    f_name = fit_font(draw, name_text, "Orbitron-VariableFont_wght.ttf", max_w=W - col_name - right_pad, start_size=S(44), min_size=S(26))
    f_pts  = load_font("Michroma-Regular.ttf", S(68))
    f_label = load_font("DejaVuSans-Bold.ttf", S(18))
    f_title = load_font("DejaVuSans-Bold.ttf", S(22))
    f_value = load_font("DejaVuSans-Bold.ttf", S(22))
    f_prog  = load_font("DejaVuSans-Bold.ttf", S(13))

    move_text = (p_move or "").upper()
    f_move = fit_font(draw, move_text, "DejaVuSans-Bold.ttf", max_w=W - col_name - right_pad, start_size=S(26), min_size=S(16))

    # Name
    draw.text((col_name, S(38)), name_text, font=f_name, fill=WHITE)
    name_w = text_width(draw, name_text, f_name)
    draw.line([(col_name, S(90)), (col_name + name_w, S(90))], fill=(rc[0], rc[1], rc[2], 160), width=S(3))

    # Rank · Title
    clean_cur = clean_rank_name(current_rank_raw)
    draw.text((col_name, S(100)), clean_cur, font=f_title, fill=(rc[0], rc[1], rc[2], 255))
    rank_w = text_width(draw, clean_cur, f_title)
    draw.text((col_name + rank_w + S(10), S(102)), "·", font=f_value, fill=MUTED)
    draw.text((col_name + rank_w + S(26), S(100)), p_title or "", font=f_title, fill=WHITE)

    # Divider
    draw.line([(col_name, S(140)), (W - right_pad, S(140))], fill=DIM, width=S(2))

    # Rating
    draw.text((col_name, S(150)), "RATING", font=f_label, fill=MUTED)
    draw.text((col_name, S(174)), str(pts), font=f_pts, fill=(rc[0], rc[1], rc[2], 255))

    # Record + WR
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0
    draw.text((col_stats, S(150)), "RECORD", font=f_label, fill=MUTED)
    draw.text((col_stats, S(174)), f"{wins}W – {losses}L", font=f_value, fill=WHITE)
    draw.text((col_stats, S(204)), f"{wr}% win rate", font=f_prog, fill=MUTED)

    # Streak
    streak_col = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    draw.text((col_stats, S(252)), "STREAK", font=f_label, fill=MUTED)
    streak_label = f"{streak} Wins 🔥" if streak >= 3 else f"{streak} Wins"
    draw.text((col_stats, S(276)), streak_label, font=f_value, fill=streak_col)

    # Divider
    draw.line([(col_name, S(325)), (W - right_pad, S(325))], fill=DIM, width=S(2))

    # Signature move
    draw.text((col_name, S(334)), "SIGNATURE MOVE", font=f_label, fill=MUTED)
    draw.text((col_name, S(358)), move_text, font=f_move, fill=WHITE)

    # Progress bar
    bar_x = col_name
    bar_y = S(422)
    badge_slot = S(52)
    bar_w = (W - col_name - right_pad - badge_slot - S(10))
    bar_h = S(10)

    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((bar_x, bar_y - S(22)), f"{int(pct * 100)}% to {clean_next}", font=f_prog, fill=MUTED)
    else:
        draw.text((bar_x, bar_y - S(22)), "MAX RANK REACHED", font=f_prog, fill=(rc[0], rc[1], rc[2], 255))

    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=S(6), fill=(28, 28, 34, 255))
    fill_w = int(bar_w * max(0.0, min(float(pct), 1.0)))
    if fill_w > 0:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=S(6), fill=(rc[0], rc[1], rc[2], 255))

    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(4))
        if next_badge:
            card.paste(next_badge, (bar_x + bar_w + S(12), bar_y + bar_h // 2 - (badge_slot - S(4)) // 2), next_badge)

    # Downscale to final size
    final = card.resize((W // SCALE, H // SCALE), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    final.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
