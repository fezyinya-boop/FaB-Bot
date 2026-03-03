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
# ---------------------------
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
    tint: Tuple[int, int, int, int] = (120, 60, 180, 26),
) -> Image.Image:
    """
    Banner-friendly anime background:
    - cover-fit crop, optional right bias
    - blur + slight bloom
    - purple tint for "arena magic" vibe
    """
    W, H = base.size
    art = art.convert("RGBA")

    # --- cover-fit with optional right bias
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

    # subtle tint
    if tint and tint[3] > 0:
        out = Image.alpha_composite(out, Image.new("RGBA", (W, H), tint))

    # soft bloom
    bright_pass = ImageEnhance.Brightness(out).enhance(1.15).filter(ImageFilter.GaussianBlur(radius=6))
    out = ImageChops.screen(out, bright_pass)

    return out


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
    # ----------------------------
    # New dimensions (premium 2:1)
    # ----------------------------
    SCALE = 2  # keep 2x render -> downscale for crisp UI
    OUT_W, OUT_H = 1024, 512
    W, H = OUT_W * SCALE, OUT_H * SCALE

    def S(x: int) -> int:
        return x * SCALE

    rc = rank_color
    WHITE: RGBA = (238, 236, 232, 255)
    MUTED: RGBA = (155, 155, 165, 255)
    SOFT: RGBA  = (255, 255, 255, 40)

    # ----------------------------
    # Base
    # ----------------------------
    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    # ----------------------------
    # Banner (anime art lives here)
    # ----------------------------
    banner_h = S(210)
    banner = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))

    bg_path = os.path.join(ASSETS_DIR, "arena_bg.png")
    if os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert("RGBA")
            banner = apply_anime_arena_background(
                banner,
                bg,
                focus_right=True,
                art_strength=0.95,
                blur_px=6,
                saturation=1.18,
                brightness=0.82,
                contrast=1.08,
                tint=(120, 60, 180, 22),
            )
        except Exception as e:
            print(f"Background overlay error: {e}")

    # Add a top-to-bottom dark fade over banner so text can sit on it if needed
    fade = Image.new("L", (W, banner_h), 0)
    fd = ImageDraw.Draw(fade)
    fd.rectangle((0, 0, W, banner_h), fill=180)
    fade = fade.filter(ImageFilter.GaussianBlur(radius=S(18)))
    fade_rgba = Image.new("RGBA", (W, banner_h), (0, 0, 0, 255))
    fade_rgba.putalpha(fade)
    banner = Image.alpha_composite(banner, fade_rgba)

    card.paste(banner, (0, 0), banner)

    # ----------------------------
    # Info panel (solid glass)
    # ----------------------------
    panel_y = banner_h - S(28)  # slightly overlaps the banner
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)

    # large rounded glass panel on the right
    panel_pad_l = S(280)
    panel_pad_r = S(26)
    panel_pad_t = panel_y + S(18)
    panel_pad_b = H - S(26)

    pd.rounded_rectangle(
        (panel_pad_l, panel_pad_t, W - panel_pad_r, panel_pad_b),
        radius=S(26),
        fill=(0, 0, 0, 205),
        outline=(255, 255, 255, 26),
        width=S(2),
    )

    # a thinner strip under the banner for separation
    pd.rectangle((0, panel_y, W, panel_y + S(2)), fill=(255, 255, 255, 18))

    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # ----------------------------
    # Avatar (overlaps banner + panel)
    # ----------------------------
    av_size = S(240)
    av_x = S(38)
    av_y = S(78)

    if avatar_img is None:
        avatar_img = Image.new("RGBA", (av_size, av_size), (25, 25, 28, 255))
    else:
        avatar_img = center_crop_square(avatar_img.convert("RGBA"))

    av = avatar_img.resize((av_size, av_size), Image.Resampling.LANCZOS)

    # soft glow behind avatar
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

    # ring
    ring_rect = (av_x - S(6), av_y - S(6), av_x + av_size + S(6), av_y + av_size + S(6))
    draw.ellipse(ring_rect, outline=(rc[0], rc[1], rc[2], 230), width=S(5))
    card.paste(av_circ, (av_x, av_y), av_circ)

    # current badge overlap
    badge_size = S(78)
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        bx = av_x + av_size - S(58)
        by = av_y + av_size - S(58)
        card.paste(cur_badge, (bx, by), cur_badge)

    # ----------------------------
    # Text + stats layout (inside panel)
    # ----------------------------
    col_left = panel_pad_l + S(28)
    col_right = W - panel_pad_r - S(28)
    col_mid = col_left + int((col_right - col_left) * 0.62)

    # Fonts (use your existing hard-coded filenames)
    name_text = (display_name or "PLAYER").upper()
    move_text = (p_move or "").upper()

    f_name = fit_font(draw, name_text, "Orbitron-VariableFont_wght.ttf", max_w=col_right - col_left, start_size=S(46), min_size=S(28))
    f_big  = load_font("Michroma-Regular.ttf", S(76))
    f_h2   = load_font("DejaVuSans-Bold.ttf", S(24))
    f_lab  = load_font("DejaVuSans-Bold.ttf", S(18))
    f_val  = load_font("DejaVuSans-Bold.ttf", S(24))
    f_small= load_font("DejaVuSans-Bold.ttf", S(14))
    f_move = fit_font(draw, move_text, "DejaVuSans-Bold.ttf", max_w=col_right - col_left, start_size=S(28), min_size=S(16))

    # Header area (name + rank + title) sits on banner but aligned to panel
    header_y = S(36)
    stroke = (0, 0, 0, 200)

    draw.text((col_left, header_y), name_text, font=f_name, fill=WHITE, stroke_width=S(2), stroke_fill=stroke)

    clean_cur = clean_rank_name(current_rank_raw)
    header2_y = header_y + S(58)
    draw.text((col_left, header2_y), clean_cur, font=f_h2, fill=(rc[0], rc[1], rc[2], 255), stroke_width=S(2), stroke_fill=stroke)
    rank_w = text_width(draw, clean_cur, f_h2)
    draw.text((col_left + rank_w + S(12), header2_y + S(2)), "·", font=f_h2, fill=(255, 255, 255, 170), stroke_width=S(2), stroke_fill=stroke)
    draw.text((col_left + rank_w + S(30), header2_y), (p_title or ""), font=f_h2, fill=WHITE, stroke_width=S(2), stroke_fill=stroke)

    # Inside panel content
    content_top = panel_pad_t + S(26)

    # Left block: rating
    draw.text((col_left, content_top), "RATING", font=f_lab, fill=MUTED)
    draw.text((col_left, content_top + S(28)), str(pts), font=f_big, fill=(rc[0], rc[1], rc[2], 255), stroke_width=S(2), stroke_fill=(0, 0, 0, 160))

    # Right block: record / winrate / streak
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    right_x = col_mid + S(22)
    draw.text((right_x, content_top), "RECORD", font=f_lab, fill=MUTED)
    draw.text((right_x, content_top + S(28)), f"{wins}W – {losses}L", font=f_val, fill=WHITE, stroke_width=S(2), stroke_fill=(0, 0, 0, 150))
    draw.text((right_x, content_top + S(62)), f"{wr}% win rate", font=f_small, fill=MUTED)

    draw.text((right_x, content_top + S(102)), "STREAK", font=f_lab, fill=MUTED)
    streak_col = (rc[0], rc[1], rc[2], 255) if streak >= 3 else WHITE
    streak_label = f"{streak} Wins 🔥" if streak >= 3 else f"{streak} Wins"
    draw.text((right_x, content_top + S(130)), streak_label, font=f_val, fill=streak_col, stroke_width=S(2), stroke_fill=(0, 0, 0, 150))

    # Divider line
    div_y = content_top + S(210)
    draw.line([(col_left, div_y), (col_right, div_y)], fill=SOFT, width=S(2))

    # Signature move
    draw.text((col_left, div_y + S(16)), "SIGNATURE MOVE", font=f_lab, fill=MUTED)
    draw.text((col_left, div_y + S(44)), move_text, font=f_move, fill=WHITE, stroke_width=S(2), stroke_fill=(0, 0, 0, 170))

    # Progress label
    bar_y = panel_pad_b - S(58)
    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((col_left, bar_y - S(22)), f"{int(max(0.0, min(1.0, float(pct))) * 100)}% to {clean_next}", font=f_small, fill=MUTED)
    else:
        draw.text((col_left, bar_y - S(22)), "MAX RANK REACHED", font=f_small, fill=(rc[0], rc[1], rc[2], 255))

    # Progress bar
    badge_slot = S(56)
    bar_w = (col_right - col_left) - badge_slot - S(10)
    bar_h = S(12)

    # track
    draw.rounded_rectangle((col_left, bar_y, col_left + bar_w, bar_y + bar_h), radius=S(8), fill=(28, 28, 34, 255))
    # fill
    fill_w = int(bar_w * max(0.0, min(1.0, float(pct))))
    if fill_w > 0:
        draw.rounded_rectangle((col_left, bar_y, col_left + fill_w, bar_y + bar_h), radius=S(8), fill=(rc[0], rc[1], rc[2], 255))

    # next badge
    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot - S(6))
        if next_badge:
            card.paste(next_badge, (col_left + bar_w + S(14), bar_y + bar_h // 2 - (badge_slot - S(6)) // 2), next_badge)

    # ----------------------------
    # Final downscale
    # ----------------------------
    final = card.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    final.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
