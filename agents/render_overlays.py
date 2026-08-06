import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def generate_starfield_png(output_path, width=1080, height=1920, seed=7):
    """Generate a deterministic deep-space starfield PNG with PIL."""
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    # Vertical deep-space gradient (dark navy -> faint purple glow at bottom)
    for y in range(height):
        t = y / height
        r = int(6 + 8 * t)
        g = int(8 + 14 * t)
        b = int(30 + 70 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    # Small white stars
    for _ in range(1400):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        sz = rng.choice([1, 1, 1, 2, 2, 3])
        b = rng.randint(140, 255)
        draw.ellipse([x, y, x + sz, y + sz], fill=(b, b, b))
    # A few larger colorful stars with glow
    for _ in range(30):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        c = rng.choice([(200, 220, 255), (255, 220, 200), (220, 200, 255), (255, 255, 220)])
        draw.ellipse([x, y, x + 3, y + 3], fill=c)
        draw.ellipse([x - 1, y - 1, x + 4, y + 4], outline=c)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path


def generate_background_video(output_path, canvas_w=720, canvas_h=1280, fps=30, duration=30, starfield_png=None):
    """Create a slow-zoom space background video from a starfield image using FFmpeg zoompan."""
    if not starfield_png or not os.path.exists(starfield_png):
        starfield_png = generate_starfield_png(
            os.path.join(os.path.dirname(output_path), "starfield.png")
        )
    frames = int(duration * fps)
    zoom_end = 1.15
    vf = (
        f"scale=1080:1920,"
        f"zoompan=z='min(1+({zoom_end}-1)*on/{frames},{zoom_end})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={canvas_w}x{canvas_h}:fps={fps}"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", starfield_png,
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def render_fact_overlay(text, cfg, canvas_w, canvas_h, output_path):
    """Render the interesting fact as a full-canvas transparent overlay PNG."""
    ft = cfg.get("fact_text", {})
    font = _load_font(ft.get("font", FONT_BOLD), int(ft.get("font_size", 34)))
    text_color = ft.get("text_color", "#FFFFFF")
    box_color = ft.get("box_color", "#00000099")
    max_lines = int(ft.get("max_lines", 2))
    max_chars = int(ft.get("max_chars_per_line", 34))
    padding = int(ft.get("padding", 18))
    bottom_margin = int(ft.get("bottom_margin", 24))

    # Wrap text into lines
    words = str(text).split()
    lines = []
    cur = ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if not lines:
        lines = [text]
    lines = lines[:max_lines]

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    line_h = int(ft.get("font_size", 34)) + 14
    box_h = len(lines) * line_h + padding
    bbox = draw.textbbox((0, 0), " ".join(lines), font=font)
    text_w = bbox[2] - bbox[0]
    box_w = min(canvas_w - 2 * padding, text_w + 2 * padding)

    # Position near the bottom of the movie clip region
    clip_region = cfg.get("movie_clip", {}).get("region", {"x": 0, "y": 0, "width": canvas_w, "height": canvas_h})
    clip_bottom = clip_region.get("y", 0) + clip_region.get("height", canvas_h)
    y1 = max(0, clip_bottom - box_h - bottom_margin)
    x1 = (canvas_w - box_w) // 2

    draw.rounded_rectangle([x1, y1, x1 + box_w, y1 + box_h], radius=16, fill=box_color)

    yy = y1 + padding // 2 + 4
    for line in lines:
        tw = draw.textlength(line, font=font)
        tx = x1 + (box_w - tw) // 2
        draw.text((tx, yy), line, font=font, fill=text_color, stroke_width=2, stroke_fill="#000000")
        yy += line_h

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path


def render_profile_section(cfg, output_path):
    """Render the profile section placeholder image (replaced when the template image is provided)."""
    ps = cfg.get("profile_section", {})
    region = ps.get("region", {"x": 0, "y": 760, "width": 720, "height": 220})
    w = int(region["width"])
    h = int(region["height"])

    img = Image.new("RGBA", (w, h), ps.get("bg_color", "#0d0d1a"))
    draw = ImageDraw.Draw(img)
    draw.line([(0, 0), (w, 0)], fill="#ffffff22", width=2)

    # Avatar circle with play triangle placeholder
    avatar_r = int(h * 0.30)
    cx = int(w * 0.16)
    cy = int(h * 0.45)
    draw.ellipse([cx - avatar_r, cy - avatar_r, cx + avatar_r, cy + avatar_r],
                 fill="#3a3a6a", outline="#ffffff66", width=3)
    draw.polygon([(cx - 14, cy - 12), (cx - 14, cy + 12), (cx + 16, cy)], fill="#FFFFFF")

    # Handle / name
    font_name = _load_font(FONT_BOLD, int(h * 0.17))
    font_sub = _load_font(FONT_REG, int(h * 0.12))
    tx = cx + avatar_r + 24
    draw.text((tx, int(h * 0.22)), ps.get("placeholder_text", "PROFILE"), font=font_name, fill="#FFFFFF")
    draw.text((tx, int(h * 0.52)), ps.get("placeholder_subtext", "Template coming soon"), font=font_sub, fill="#AAAAAA")

    # Follow button placeholder
    btn_w = int(w * 0.18)
    btn_h = int(h * 0.28)
    bx = w - btn_w - 24
    by = int((h - btn_h) / 2)
    draw.rounded_rectangle([bx, by, bx + btn_w, by + btn_h], radius=int(btn_h / 2), fill="#FFFFFF")
    ffont = _load_font(FONT_BOLD, int(h * 0.13))
    fw = draw.textlength("Follow", font=ffont)
    draw.text((bx + (btn_w - fw) / 2, by + btn_h / 2 - int(h * 0.07)), "Follow", font=ffont, fill="#000000")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path
