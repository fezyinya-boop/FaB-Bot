from PIL import Image, ImageDraw, ImageFont, ImageFilter
import aiohttp
import io
import os
import re
import math

# --- FONTS ---
def load_custom_font(font_filename, size):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", font_filename)
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    for path in [
        '/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-bold.otf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- FETCH AVATAR ---
async def fetch_avatar(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url), timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert('RGBA')
    except Exception as e:
        print(f"Avatar fetch error: {e}")
    return None

# --- RANK UTILS ---
def clean_rank_name(name: str) -> str:
    return re.sub(r'<:[^:]+:\d+>\s*', '', name).strip()

BADGES_DIR = os.path.join(os.path.dirname(__file__), 'badges')
RANK_BADGES = {
    "DIAMOND":  os.path.join(BADGES_DIR, 'rank_diamond.png'),
    "PLATINUM": os.path.join(BADGES_DIR, 'rank_platinum.png'),
    "GOLD":     os.path.join(BADGES_DIR, 'rank_gold.png'),
    "SILVER":   os.path.join(BADGES_DIR, 'rank_silver.png'),
    "BRONZE":   os.path.join(BADGES_DIR, 'rank_bronze.png'),
}

def get_rank_badge(rank_name_raw: str, size: int = 60):
    clean = clean_rank_name(rank_name_raw).upper()
    path = RANK_BADGES.get(clean)
    if not path or not os.path.exists(path):
        return None
    try:
        return Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS)
    except:
        return None


# --- DRAWING HELPERS ---

def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    r = radius
    if fill:
        draw.rectangle([x1+r, y1, x2-r, y2], fill=fill)
        draw.rectangle([x1, y1+r, x2, y2-r], fill=fill)
        draw.ellipse([x1, y1, x1+2*r, y1+2*r], fill=fill)
        draw.ellipse([x2-2*r, y1, x2, y1+2*r], fill=fill)
        draw.ellipse([x1, y2-2*r, x1+2*r, y2], fill=fill)
        draw.ellipse([x2-2*r, y2-2*r, x2, y2], fill=fill)
    if outline:
        draw.arc([x1, y1, x1+2*r, y1+2*r], 180, 270, fill=outline, width=width)
        draw.arc([x2-2*r, y1, x2, y1+2*r], 270, 360, fill=outline, width=width)
        draw.arc([x1, y2-2*r, x1+2*r, y2], 90, 180, fill=outline, width=width)
        draw.arc([x2-2*r, y2-2*r, x2, y2], 0, 90, fill=outline, width=width)
        draw.line([x1+r, y1, x2-r, y1], fill=outline, width=width)
        draw.line([x1+r, y2, x2-r, y2], fill=outline, width=width)
        draw.line([x1, y1+r, x1, y2-r], fill=outline, width=width)
        draw.line([x2, y1+r, x2, y2-r], fill=outline, width=width)

def make_noise_texture(w, h, intensity=6):
    """Subtle noise overlay for background texture."""
    import random
    noise = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    px = noise.load()
    for y in range(h):
        for x in range(w):
            v = random.randint(-intensity, intensity)
            px[x, y] = (max(0, min(255, 128+v)), max(0, min(255, 128+v)), max(0, min(255, 128+v)), 18)
    return noise


# --- CORE CARD GENERATOR ---
def make_profile_card(
    display_name, p_title, p_move, pts, wins, losses, streak, pct,
    current_rank_raw, next_rank_raw, rank_color, avatar_img=None
):
    W, H = 940, 480
    rc = rank_color  # shorthand

    # ── BASE BACKGROUND ──────────────────────────────────────────────────────
    card = Image.new('RGBA', (W, H), (8, 8, 10, 255))
    draw = ImageDraw.Draw(card)

    # Diagonal gradient bands (very subtle)
    for i in range(W + H):
        alpha = int(6 * math.sin(i / (W + H) * math.pi))
        shade = max(0, 10 + alpha)
        if i < W:
            draw.line([(i, 0), (0, i)], fill=(shade, shade, shade+2, 255))

    # Radial glow from top-left (where avatar will be)
    for r in range(300, 0, -10):
        a = int(15 * (1 - r / 300) ** 2)
        draw.ellipse([(40-r, 40-r), (40+r, 40+r)], fill=(*rc, a))

    # Noise texture overlay
    noise = make_noise_texture(W, H, intensity=5)
    card = Image.alpha_composite(card, noise)
    draw = ImageDraw.Draw(card)

    # ── RANK-COLORED LEFT ACCENT BAR ─────────────────────────────────────────
    # Bold vertical bar on far left edge
    bar_thickness = 5
    draw.rectangle([(0, 0), (bar_thickness, H)], fill=(*rc, 255))

    # Glow behind the bar
    for gi in range(20, 0, -2):
        ga = int(40 * (gi / 20) ** 2)
        draw.rectangle([(bar_thickness, gi*2), (bar_thickness + gi, H - gi*2)],
                       fill=(*rc, ga))

    # ── AVATAR SECTION (left panel, slightly tinted) ──────────────────────────
    av_panel_w = 275
    # Subtle tinted left panel
    panel = Image.new('RGBA', (av_panel_w, H), (*rc, 8))
    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # Vertical separator line
    draw.line([(av_panel_w, 20), (av_panel_w, H-20)], fill=(*rc, 40), width=1)

    av_size = 210
    av_x = bar_thickness + 24
    av_y = (H - av_size) // 2

    if not avatar_img:
        avatar_img = Image.new('RGBA', (av_size, av_size), (20, 20, 22, 255))

    av = avatar_img.resize((av_size, av_size), Image.LANCZOS)
    mask = Image.new('L', (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (av_size-1, av_size-1)], fill=255)
    av_circ = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
    av_circ.paste(av, mask=mask)

    # Outer glow ring (blurred effect via layered ellipses)
    for gi in range(16, 0, -2):
        ga = int(60 * (1 - gi/16) ** 1.5)
        draw.ellipse(
            [(av_x - gi, av_y - gi), (av_x + av_size + gi, av_y + av_size + gi)],
            outline=(*rc, ga), width=2
        )
    # Solid ring
    draw.ellipse(
        [(av_x - 4, av_y - 4), (av_x + av_size + 4, av_y + av_size + 4)],
        outline=(*rc, 220), width=3
    )

    card.paste(av_circ, (av_x, av_y), av_circ)

    # Rank badge on avatar corner
    badge_size = 68
    cur_badge = get_rank_badge(current_rank_raw, size=badge_size)
    if cur_badge:
        bx = av_x + av_size - 54
        by = av_y + av_size - 54
        # Dark circle behind badge
        draw.ellipse([(bx-6, by-6), (bx+badge_size+6, by+badge_size+6)],
                     fill=(6, 6, 8, 255), outline=(*rc, 120), width=2)
        card.paste(cur_badge, (bx, by), cur_badge)

    # ── FONTS ──────────────────────────────────────────────────────────────────
    f_name   = load_custom_font("Orbitron-VariableFont_wght.ttf", 40)
    f_pts    = load_custom_font("Michroma-Regular.ttf", 64)
    f_rp     = load_custom_font("Michroma-Regular.ttf", 14)
    f_label  = load_custom_font("Michroma-Regular.ttf", 10)
    f_title  = load_custom_font("PirataOne-Regular.ttf", 28)
    f_value  = load_custom_font("FunnelSans-VariableFont_wght.ttf", 22)
    f_prog   = load_custom_font("FunnelSans-VariableFont_wght.ttf", 13)

    # Muted label color and white value color
    LABEL  = (90, 90, 100)
    WHITE  = (235, 232, 228)
    DIM    = (55, 55, 65)

    # ── RIGHT CONTENT AREA ───────────────────────────────────────────────────
    cx = av_panel_w + 28   # content x start
    col_r = 680            # right stat column x

    # ── NAME ─────────────────────────────────────────────────────────────────
    draw.text((cx, 38), display_name.upper(), font=f_name, fill=WHITE)

    # Thin underline beneath name (rank-colored)
    name_bbox = draw.textbbox((cx, 38), display_name.upper(), font=f_name)
    name_w = name_bbox[2] - name_bbox[0]
    draw.line([(cx, 88), (cx + name_w, 88)], fill=(*rc, 160), width=2)

    # ── RANK · TITLE ──────────────────────────────────────────────────────────
    clean_cur = clean_rank_name(current_rank_raw)
    # Rank in rank color, title in white
    draw.text((cx, 98), clean_cur, font=f_title, fill=(*rc, 255))
    rank_bbox = draw.textbbox((cx, 98), clean_cur, font=f_title)
    dot_x = rank_bbox[2] + 10
    draw.text((dot_x, 102), "·", font=f_value, fill=LABEL)
    draw.text((dot_x + 18, 98), p_title, font=f_title, fill=WHITE)

    # ── SECTION DIVIDER ───────────────────────────────────────────────────────
    draw.line([(cx, 142), (W - 24, 142)], fill=DIM, width=1)

    # ── RATING ───────────────────────────────────────────────────────────────
    draw.text((cx, 152), "RATING", font=f_label, fill=LABEL)
    draw.text((cx, 168), str(pts), font=f_pts, fill=(*rc, 255))
    # "RP" sits to the right of the number at baseline
    pts_bbox = draw.textbbox((cx, 168), str(pts), font=f_pts)
    draw.text((pts_bbox[2] + 6, 218), "RP", font=f_rp, fill=LABEL)

    # ── RIGHT STATS COLUMN ────────────────────────────────────────────────────
    total = wins + losses
    wr = round((wins / total) * 100) if total > 0 else 0

    # RECORD
    draw.text((col_r, 152), "RECORD", font=f_label, fill=LABEL)
    draw.text((col_r, 170), f"{wins}W – {losses}L", font=f_value, fill=WHITE)
    draw.text((col_r, 200), f"{wr}% win rate", font=f_prog, fill=LABEL)

    # STREAK
    streak_col = (*rc, 255) if streak >= 3 else WHITE
    draw.text((col_r, 248), "STREAK", font=f_label, fill=LABEL)
    streak_text = f"{streak} Wins  🔥" if streak >= 3 else f"{streak} Wins"
    draw.text((col_r, 266), streak_text, font=f_value, fill=streak_col)

    # ── SECTION DIVIDER ───────────────────────────────────────────────────────
    draw.line([(cx, 340), (W - 24, 340)], fill=DIM, width=1)

    # ── SIGNATURE MOVE ────────────────────────────────────────────────────────
    draw.text((cx, 350), "SIGNATURE MOVE", font=f_label, fill=LABEL)
    draw.text((cx, 368), p_move.upper(), font=f_value, fill=WHITE)

    # ── PROGRESS BAR ──────────────────────────────────────────────────────────
    bar_x = cx
    bar_y = 430
    badge_slot = 48
    bar_w = W - cx - 28 - badge_slot - 14
    bar_h = 8
    bar_r = 4  # corner radius

    # Progress label
    if next_rank_raw:
        clean_next = clean_rank_name(next_rank_raw)
        draw.text((bar_x, bar_y - 20), f"{int(pct*100)}% to {clean_next}",
                  font=f_prog, fill=LABEL)
    else:
        draw.text((bar_x, bar_y - 20), "MAX RANK REACHED",
                  font=f_prog, fill=(*rc, 255))

    # Track (rounded)
    draw_rounded_rect(draw,
                      (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                      radius=bar_r, fill=(30, 30, 35))

    # Fill (rounded)
    fill_w = max(bar_r * 2, int(bar_w * min(pct, 1.0)))
    draw_rounded_rect(draw,
                      (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
                      radius=bar_r, fill=(*rc, 255))

    # Glow tip on fill end
    gx = bar_x + fill_w
    for gi in range(12, 0, -1):
        ga = int(55 * (gi / 12) ** 2)
        draw.ellipse([(gx - gi, bar_y - gi//2), (gx + gi, bar_y + bar_h + gi//2)],
                     fill=(*rc, ga))

    # Next rank badge to the right of bar
    if next_rank_raw:
        next_badge = get_rank_badge(next_rank_raw, size=badge_slot)
        if next_badge:
            bx2 = bar_x + bar_w + 14
            by2 = bar_y + bar_h // 2 - badge_slot // 2
            draw.ellipse([(bx2-4, by2-4), (bx2+badge_slot+4, by2+badge_slot+4)],
                         fill=(12, 12, 14, 255), outline=(*rc, 60), width=1)
            card.paste(next_badge, (bx2, by2), next_badge)

    # ── BOTTOM RANK WATERMARK (very subtle) ──────────────────────────────────
    wm_text = clean_rank_name(current_rank_raw).upper()
    try:
        f_wm = load_custom_font("Orbitron-VariableFont_wght.ttf", 110)
        wm_bbox = draw.textbbox((0, 0), wm_text, font=f_wm)
        wm_w = wm_bbox[2] - wm_bbox[0]
        wm_x = W - wm_w - 20
        wm_y = H - 110
        # Draw as very faint watermark
        wm_layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        wm_draw = ImageDraw.Draw(wm_layer)
        wm_draw.text((wm_x, wm_y), wm_text, font=f_wm, fill=(*rc, 18))
        card = Image.alpha_composite(card, wm_layer)
        draw = ImageDraw.Draw(card)
    except:
        pass

    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    return buf
    
