import os
import sys
import asyncio
import json
import subprocess
from loguru import logger
from datetime import datetime, timezone

from memory_agent import async_get_latest_video_id, async_get_memory, async_update_memory
from render_overlays import (
    generate_background_video,
    generate_starfield_png,
    render_fact_overlay,
    render_profile_section,
    generate_red_arrow_png,
)

CONFIG_FILE = "layout_config.json"
ASSETS_DIR = "assets"
EXPORTS_DIR = "exports"


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_background(cfg):
    bg = cfg.get("background", {})
    asset = bg.get("asset", f"{ASSETS_DIR}/background_gradient.mp4")
    if os.path.exists(asset):
        return asset
    if not bg.get("auto_generate", True):
        raise FileNotFoundError(f"Background asset not found: {asset}")
    canvas = cfg.get("canvas", {"width": 720, "height": 1280, "fps": 30})
    duration = int(bg.get("generate_duration", 30))
    logger.info(f"Generating background video: {asset} ({duration}s)")
    generate_background_video(
        asset,
        canvas_w=int(canvas["width"]),
        canvas_h=int(canvas["height"]),
        fps=int(canvas.get("fps", 30)),
        duration=duration,
        top_color=bg.get("bg_color_top", "#F5EFEB"),
        bottom_color=bg.get("bg_color_bottom", "#E5D9D3")
    )
    return asset


def has_audio_stream(path):
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True
        )
        return bool(probe.stdout.strip())
    except Exception:
        return False


def ffmpeg_probe_duration(path):
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, check=True
        )
        return float(probe.stdout.strip())
    except Exception:
        return None


def build_ffmpeg_command(cfg, video_id, clip_path, bg_path, fact_png, profile_png, reaction_path, clip_duration, arrow_x, arrow_y):
    canvas = cfg["canvas"]
    W, H = int(canvas["width"]), int(canvas["height"])

    clip_region = cfg["movie_clip"]["region"]
    cw, ch = int(clip_region["width"]), int(clip_region["height"])
    cx, cy = int(clip_region["x"]), int(clip_region["y"])

    card_region = cfg.get("card", {"x": 40, "y": 80, "width": 640, "height": 760})
    pw, ph = int(card_region["width"]), int(card_region["height"])
    px, py = int(card_region["x"]), int(card_region["y"])

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    # Inputs
    cmd += ["-i", bg_path]
    cmd += ["-i", clip_path]
    input_idx = 2
    if fact_png:
        cmd += ["-loop", "1", "-framerate", str(canvas["fps"]), "-i", fact_png]
        input_idx += 1
    cmd += ["-loop", "1", "-framerate", str(canvas["fps"]), "-i", profile_png]
    input_idx += 1
    reaction_input_idx = None
    if reaction_path:
        cmd += ["-stream_loop", "-1", "-i", reaction_path]
        reaction_input_idx = input_idx
        input_idx += 1

    # Red Arrow Overlay Input
    arrow_png = f"{ASSETS_DIR}/red_arrow.png"
    generate_red_arrow_png(arrow_png)
    cmd += ["-loop", "1", "-framerate", str(canvas["fps"]), "-i", arrow_png]
    arrow_input_idx = input_idx
    input_idx += 1

    # Filter graph
    parts = []
    parts.append(f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setpts=PTS-STARTPTS,format=yuv420p[bg]")
    parts.append(f"[1:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},setpts=PTS-STARTPTS[clip]")
    
    # 1. Overlay profile/card png onto background
    profile_input_idx = 3 if fact_png else 2
    parts.append(f"[bg][{profile_input_idx}:v]overlay={px}:{py}[bgp]")
    
    # 2. Overlay clip onto card background
    parts.append(f"[bgp][clip]overlay={cx}:{cy}[bgpc]")
    cur_label = "bgpc"

    # 3. Overlay fact text on top of everything inside the card
    if fact_png:
        parts.append(f"[{cur_label}][2:v]overlay=0:0[bgpcf]")
        cur_label = "bgpcf"

    # 4. Overlay red arrow pointing to the main subject with bounce animation
    arrow_w, arrow_h = 80, 80
    ax = cx + int((arrow_x or 0.5) * cw) - (arrow_w // 2)
    ay = cy + int((arrow_y or 0.5) * ch) - arrow_h - 15
    ay = max(cy + 10, ay) # Clamp arrow Y so it never goes above the movie clip region (fact text card)
    bounce_expression = f"({ay}) - 15 + 15*sin(6.28318*t/0.8)"
    
    parts.append(f"[{arrow_input_idx}:v]scale={arrow_w}:{arrow_h}[arrow_scaled]")
    parts.append(f"[{cur_label}][arrow_scaled]overlay={ax}:{bounce_expression}:shortest=1[{cur_label}_arrow]")
    cur_label = f"{cur_label}_arrow"

    if reaction_path:
        reaction_region = cfg["reaction_character"]["region"]
        rw, rh = int(reaction_region["width"]), int(reaction_region["height"])
        rx, ry = int(reaction_region["x"]), int(reaction_region["y"])
        parts.append(f"[{reaction_input_idx}:v]crop=608:1080:656:0,scale={rw}:{rh}:force_original_aspect_ratio=increase,crop={rw}:{rh},chromakey=0x00FF00:0.25:0.03,setpts=PTS-STARTPTS[react]")
        parts.append(f"[{cur_label}][react]overlay={rx}:{ry}:shortest=1[outv]")
        video_label = "outv"
    else:
        parts.append(f"[{cur_label}]null[outv]")
        video_label = "outv"

    # Audio: clip audio + (optional) reaction audio
    clip_has_audio = has_audio_stream(clip_path)
    reaction_has_audio = reaction_path and has_audio_stream(reaction_path)
    include_reaction_audio = bool(reaction_path) and cfg.get("reaction_character", {}).get("include_audio", False)

    audio_label = None
    audio_kind = None  # "filter" -> filtergraph output label, "stream" -> input stream specifier
    if clip_has_audio:
        parts.append("[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1]")
        if include_reaction_audio and reaction_has_audio:
            parts.append(f"[{reaction_input_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[a4]")
            parts.append("[a1][a4]amix=inputs=2:duration=first:normalize=0[aout]")
            audio_label, audio_kind = "aout", "filter"
        else:
            audio_label, audio_kind = "a1", "filter"
    elif include_reaction_audio and reaction_has_audio:
        parts.append(f"[{reaction_input_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[a4]")
        audio_label, audio_kind = "a4", "filter"

    cmd += ["-filter_complex", ";".join(parts)]

    out_path = f"{EXPORTS_DIR}/{video_id}_final.mp4"
    cmd += ["-map", f"[{video_label}]"]
    if audio_label:
        cmd += ["-map", f"[{audio_label}]" if audio_kind == "filter" else audio_label]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_label:
        cmd += ["-c:a", "aac"]
    cmd += ["-shortest"]
    if clip_duration:
        cmd += ["-t", f"{clip_duration:.3f}"]
    cmd += [out_path]

    return cmd, out_path


async def edit_video():
    video_id = await async_get_latest_video_id()
    if not video_id:
        logger.error("No video_id found in memory.")
        sys.exit(1)

    memory = await async_get_memory(video_id)
    clip_path = memory.clip_path
    fact_text = memory.fact_text

    if not clip_path or not os.path.exists(clip_path):
        logger.error(f"Clip path {clip_path} not found in memory.")
        sys.exit(1)

    logger.info("Composing final Shorts video (gradient background + clip + facts + profile + reaction)...")

    cfg = load_config()
    canvas = cfg["canvas"]
    clip_duration = memory.clip_duration or ffmpeg_probe_duration(clip_path)

    try:
        bg_path = ensure_background(cfg)

        # Reaction character video (optional)
        reaction_path = None
        reaction_cfg = cfg.get("reaction_character", {})
        if reaction_cfg.get("enabled", True):
            import shutil
            import hashlib
            rx_dir = r"C:\Users\admin\Documents\reaction charactor"
            if not os.path.exists(rx_dir):
                rx_dir = os.path.join(ASSETS_DIR, "reaction_characters")
            if os.path.exists(rx_dir) and not os.environ.get("BATCH_TEST"):
                files = [os.path.join(rx_dir, f) for f in os.listdir(rx_dir) if f.endswith(".mp4")]
                if files:
                    idx = int(hashlib.md5(video_id.encode('utf-8')).hexdigest(), 16) % len(files)
                    selected_rx = files[idx]
                    logger.info(f"Selected reaction character dynamically: {selected_rx}")
                    os.makedirs(ASSETS_DIR, exist_ok=True)
                    shutil.copy(selected_rx, f"{ASSETS_DIR}/reaction.mp4")
                    reaction_path = f"{ASSETS_DIR}/reaction.mp4"

            if not reaction_path:
                candidate = reaction_cfg.get("asset", f"{ASSETS_DIR}/reaction.mp4")
                if os.path.exists(candidate):
                    reaction_path = candidate
                else:
                    logger.warning(f"Reaction character video not found at {candidate}. Skipping (will be added later).")

        # Adaptive layout: without a reaction video, we keep layout clean
        if not reaction_path:
            logger.info("No reaction video -> keeping standard layout design.")

        # Render fact text overlay
        fact_png = None
        if cfg.get("fact_text", {}).get("enabled", True) and fact_text:
            fact_png = f"{EXPORTS_DIR}/{video_id}_fact.png"
            render_fact_overlay(fact_text, cfg, int(canvas["width"]), int(canvas["height"]), fact_png)

        # Render profile section placeholder
        profile_png = f"{EXPORTS_DIR}/{video_id}_profile.png"
        if cfg.get("profile_section", {}).get("enabled", True):
            render_profile_section(cfg, profile_png)
        else:
            profile_png = None

        os.makedirs(EXPORTS_DIR, exist_ok=True)
        command, out_path = build_ffmpeg_command(
            cfg, video_id, clip_path, bg_path, fact_png, profile_png, reaction_path, clip_duration,
            memory.arrow_x, memory.arrow_y
        )

        logger.info(f"Running FFmpeg composition -> {out_path}")
        res = subprocess.run(command, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg failed with exit code {res.returncode}")
            logger.error(f"FFmpeg stderr: {res.stderr[:2000]}")
            raise Exception(f"FFmpeg error: {res.stderr[:2000]}")

        # Cleanup temp overlays
        for tmp in [fact_png, profile_png]:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

        await async_update_memory(video_id, {
            "final_video_path": out_path,
            "end_time": datetime.now(timezone.utc).isoformat()
        })
        logger.success(f"Final video composed: {out_path}")

    except Exception as e:
        logger.error(f"Error during video editing: {e}")
        await async_update_memory(video_id, {"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(edit_video())
