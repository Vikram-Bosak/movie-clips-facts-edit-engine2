import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _load_font(path, size):
    try:
        if os.name == 'nt':
            font_names = ["arialbd.ttf" if "Bold" in path else "arial.ttf", "calibrib.ttf" if "Bold" in path else "calibri.ttf"]
            for f in font_names:
                try:
                    return ImageFont.truetype(f, size)
                except Exception:
                    continue
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.load_default(size=size) # Pillow 10+ supports size
        except Exception:
            return ImageFont.load_default()


def _load_emoji_font(size):
    paths = [
        "C:\\Windows\\Fonts\\seguiemj.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Apple Color Emoji.ttf"
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return None


def generate_starfield_png(output_path, width=1080, height=1920, seed=7):
    """Fallback function to generate a starfield if needed."""
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)], fill=(int(245 - 16*t), int(239 - 20*t), int(235 - 20*t)))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path


def generate_background_video(output_path, canvas_w=720, canvas_h=1280, fps=30, duration=30, starfield_png=None, top_color="#F5EFEB", bottom_color="#E5D9D3"):
    """Create a warm beige gradient background video."""
    img = Image.new("RGB", (canvas_w, canvas_h))
    draw = ImageDraw.Draw(img)
    
    def hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 8:
            hex_str = hex_str[:6]
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
        
    c_top = hex_to_rgb(top_color)
    c_bottom = hex_to_rgb(bottom_color)
    
    for y in range(canvas_h):
        t = y / canvas_h
        r = int(c_top[0] + (c_bottom[0] - c_top[0]) * t)
        g = int(c_top[1] + (c_bottom[1] - c_top[1]) * t)
        b = int(c_top[2] + (c_bottom[2] - c_top[2]) * t)
        draw.line([(0, y), (canvas_w, y)], fill=(r, g, b))
        
    bg_png = output_path.replace(".mp4", "_temp_bg.png")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(bg_png)
    
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", bg_png,
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", f"fps={fps}",
        output_path
    ]
    subprocess.run(cmd, check=True)
    if os.path.exists(bg_png):
        os.remove(bg_png)
    return output_path


def render_fact_overlay(text, cfg, canvas_w, canvas_h, output_path):
    """Render the interesting fact text overlay inside the card area."""
    card = cfg.get("card", {"x": 40, "y": 80, "width": 640, "height": 760})
    ft = cfg.get("fact_text", {})
    font_size = int(ft.get("font_size", 24))
    font = _load_font(FONT_REG, font_size)
    font_bold = _load_font(FONT_BOLD, font_size)
    text_color = ft.get("text_color", "#FFFFFF")
    max_lines = int(ft.get("max_lines", 5))
    max_chars = int(ft.get("max_chars_per_line", 42))
    line_height = int(ft.get("line_height", 34))

    # Clean text
    text_str = str(text).replace("\n", " ").strip()
    words = text_str.split()
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
        lines = [text_str]
    lines = lines[:max_lines]

    # Full transparent canvas
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Position text in card at x = card_x + 24, y = card_y + 110
    tx = int(card.get("x", 40)) + 24
    ty = int(card.get("y", 80)) + 105

    emoji_font = _load_emoji_font(font_size)

    for line in lines:
        words_in_line = line.split(" ")
        current_x = tx
        is_bold_toggle = False
        for w in words_in_line:
            if w.startswith("**"):
                is_bold_toggle = True
                w = w[2:]
                
            is_bold = is_bold_toggle or (w.lower() in ["accidentally", "throw", "miss", "look", "like", "crack", "up", "lucky", "head", "lot"])
            
            clean_w = w
            if "**" in w:
                parts = w.split("**")
                clean_w = parts[0] + (parts[1] if len(parts) > 1 else "")
                is_bold_toggle = False
                
            # Draw clean_w + " " with emoji split
            text_to_draw = clean_w + " "
            active_font = font_bold if is_bold else font
            
            # Split text into segments of either normal characters or emoji characters
            segments = []
            cur_seg = ""
            is_cur_emoji = None
            for char in text_to_draw:
                is_emoji = ord(char) > 0xFFFF
                if is_cur_emoji is None:
                    is_cur_emoji = is_emoji
                    cur_seg += char
                elif is_cur_emoji == is_emoji:
                    cur_seg += char
                else:
                    segments.append((cur_seg, is_cur_emoji))
                    cur_seg = char
                    is_cur_emoji = is_emoji
            if cur_seg:
                segments.append((cur_seg, is_cur_emoji))
                
            for seg_text, is_emoji in segments:
                current_font = (emoji_font if emoji_font else active_font) if is_emoji else active_font
                draw.text((current_x, ty), seg_text, font=current_font, fill=text_color)
                try:
                    seg_w = draw.textlength(seg_text, font=current_font)
                except Exception:
                    bbox = draw.textbbox((0, 0), seg_text, font=current_font)
                    seg_w = bbox[2] - bbox[0]
                current_x += int(seg_w)
            
        ty += line_height

    # Draw @SpideyPunch watermark at the bottom center of the movie clip
    clip_region = cfg.get("movie_clip", {}).get("region", {"x": 60, "y": 420, "width": 600, "height": 420})
    cx, cy = int(clip_region["x"]), int(clip_region["y"])
    cw, ch = int(clip_region["width"]), int(clip_region["height"])
    
    watermark_text = cfg.get("profile_section", {}).get("placeholder_subtext", "@SpideyPunch")
    watermark_font = _load_font(FONT_BOLD, 18)
    try:
        w_width = draw.textlength(watermark_text, font=watermark_font)
    except Exception:
        w_width = draw.textbbox((0, 0), watermark_text, font=watermark_font)[2]
        
    wx = cx + (cw - int(w_width)) // 2
    wy = cy + ch - 35
    draw.text((wx, wy), watermark_text, font=watermark_font, fill=(255, 255, 255, 100))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path


def render_profile_section(cfg, output_path):
    """Render the dark container card, profile header, verification checkmark, and right-side icons."""
    card = cfg.get("card", {"x": 40, "y": 80, "width": 640, "height": 760})
    ps = cfg.get("profile_section", {})
    w = int(card["width"])
    h = int(card["height"])

    # Create image of size w x h
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw dark card background
    def parse_color(c_str):
        if c_str.startswith("#") and len(c_str) == 9: # Hex with alpha
            r = int(c_str[1:3], 16)
            g = int(c_str[3:5], 16)
            b = int(c_str[5:7], 16)
            a = int(c_str[7:9], 16)
            return (r, g, b, a)
        # Fallback to standard color
        return c_str

    bg_color = parse_color(card.get("bg_color", "#0a0a0acc"))
    border_color = parse_color(card.get("border_color", "#ffffff1a"))
    border_w = int(card.get("border_width", 2))
    radius = int(card.get("radius", 24))

    draw.rounded_rectangle(
        [0, 0, w, h],
        radius=radius,
        fill=bg_color,
        outline=border_color,
        width=border_w
    )

    # Draw profile picture (circular avatar)
    avatar_color = ps.get("avatar_color", "#ff5555")
    avatar_r = 24
    cx, cy = 24 + avatar_r, 24 + avatar_r
    
    avatar_path = "assets/avatar.png"
    if os.path.exists(avatar_path):
        try:
            avatar_img = Image.open(avatar_path).convert("RGBA")
            avatar_img = avatar_img.resize((avatar_r * 2, avatar_r * 2), Image.Resampling.LANCZOS)
            img.paste(avatar_img, (24, 24), mask=avatar_img)
        except Exception as e:
            draw.ellipse([cx - avatar_r, cy - avatar_r, cx + avatar_r, cy + avatar_r], fill=avatar_color)
            draw.polygon([(cx - 10, cy - 4), (cx - 2, cy - 6), (cx - 4, cy + 4)], fill="#FFFFFF")
            draw.polygon([(cx + 10, cy - 4), (cx + 2, cy - 6), (cx + 4, cy + 4)], fill="#FFFFFF")
    else:
        draw.ellipse([cx - avatar_r, cy - avatar_r, cx + avatar_r, cy + avatar_r], fill=avatar_color)
        draw.polygon([(cx - 10, cy - 4), (cx - 2, cy - 6), (cx - 4, cy + 4)], fill="#FFFFFF")
        draw.polygon([(cx + 10, cy - 4), (cx + 2, cy - 6), (cx + 4, cy + 4)], fill="#FFFFFF")

    # Name and Handle
    font_name = _load_font(FONT_BOLD, 22)
    font_handle = _load_font(FONT_REG, 16)
    
    name_text = ps.get("placeholder_text", "Spoody")
    handle_text = ps.get("placeholder_subtext", "@JustSpoody")
    
    draw.text((84, 22), name_text, font=font_name, fill="#FFFFFF")
    draw.text((84, 50), handle_text, font=font_handle, fill="#888888")

    # Verification Badge (gold/yellow circle with a checkmark)
    try:
        name_w = draw.textlength(name_text, font=font_name)
    except Exception:
        name_w = draw.textbbox((0, 0), name_text, font=font_name)[2]
        
    bx = 84 + int(name_w) + 8
    by = 26
    draw.ellipse([bx, by, bx + 16, by + 16], fill="#FFD700")
    draw.line([(bx + 4, by + 8), (bx + 7, by + 11), (bx + 12, by + 5)], fill="#000000", width=2)

    # Draw right side header icons (search and sync)
    # Search icon (magnifying glass)
    sx, sy = w - 44, 30
    draw.ellipse([sx, sy, sx + 12, sy + 12], outline="#FFFFFF", width=2)
    draw.line([(sx + 10, sy + 10), (sx + 16, sy + 16)], fill="#FFFFFF", width=2)

    # Sync icon (two curved arrows or simple circles)
    rx, ry = w - 84, 30
    draw.ellipse([rx, ry, rx + 12, ry + 12], outline="#FFFFFF", width=2)
    draw.line([(rx + 6, ry - 2), (rx + 6, ry + 2)], fill="#FFFFFF", width=2)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path


def generate_red_arrow_png(output_path):
    """Draw a classic, transparent Red Arrow pointing down with a white outline border."""
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Outer boundaries (white outline border)
    head_outer = [(48, 110), (152, 110), (100, 192)]
    stem_outer = [(70, 20), (130, 20), (130, 115), (70, 115)]
    
    # Inner boundaries (solid red fill)
    head_inner = [(58, 115), (142, 115), (100, 180)]
    stem_inner = [(80, 28), (120, 28), (120, 115), (80, 115)]
    
    # Draw border (white)
    draw.polygon(head_outer, fill=(255, 255, 255, 255))
    draw.polygon(stem_outer, fill=(255, 255, 255, 255))
    
    # Draw fill (red)
    draw.polygon(head_inner, fill=(255, 0, 0, 255))
    draw.polygon(stem_inner, fill=(255, 0, 0, 255))
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path


def generate_red_circle_png(output_path):
    """Draw a classic, transparent Red Circle with a white outline border."""
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw white outer circle
    draw.ellipse([20, 20, 180, 180], outline=(255, 255, 255, 255), width=8)
    # Draw red inner circle
    draw.ellipse([24, 24, 176, 176], outline=(255, 0, 0, 255), width=4)
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    return output_path
