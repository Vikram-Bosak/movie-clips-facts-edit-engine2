import os
import sys
import asyncio
import json
import subprocess
import cv2
from loguru import logger
from scenedetect import detect, ContentDetector
from faster_whisper import WhisperModel
import easyocr
from ultralytics import YOLO
from openai import OpenAI

from memory_agent import async_get_latest_video_id, async_get_memory, async_update_memory

import random
CLIP_TARGET_DURATION = float(random.randint(4, 10))
CLIP_MAX_DURATION = 10.0


def make_client():
    api_key = os.environ.get("NVIDIA_API_KEY", "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")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY environment variable is not set.")
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )


async def run_llm(client, prompt, temperature=0.5, max_tokens=1024):
    def query():
        completion = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=0.95,
            max_tokens=max_tokens,
            stream=False
        )
        return completion.choices[0].message.content.strip()
    return await asyncio.to_thread(query)


async def analyze_video():
    video_id = await async_get_latest_video_id()
    if not video_id:
        logger.error("No video_id found in memory.")
        sys.exit(1)

    memory = await async_get_memory(video_id)
    video_path = memory.local_video_path

    if not video_path or not os.path.exists(video_path):
        logger.error(f"Video path {video_path} not found.")
        sys.exit(1)

    title = memory.youtube_title or memory.original_title or "Unknown Movie Clip"
    description = memory.youtube_description or memory.original_description or ""
    channel = memory.youtube_channel or ""

    logger.info(f"Starting AI Analysis for: {title}")
    logger.info(f"Video path: {video_path}")

    client = make_client()

    try:
        # 1. Scene Detection on the full video
        logger.info("Running PySceneDetect on full video...")
        scene_list = await asyncio.to_thread(detect, video_path, ContentDetector())
        scene_analysis = [
            {
                "scene_num": i + 1,
                "start_time": scene[0].get_seconds(),
                "end_time": scene[1].get_seconds()
            }
            for i, scene in enumerate(scene_list)
        ]

        # 2. Transcription of the full video (CPU config to prevent OOM)
        logger.info("Running faster-whisper (tiny/cpu)...")
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, info = await asyncio.to_thread(model.transcribe, video_path, beam_size=5)
        raw_transcript = ""
        for segment in segments:
            raw_transcript += f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}\n"
        raw_transcript = raw_transcript.strip() or "No dialogue detected."

        # 3. Get video duration
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_duration = total_frames / fps if fps > 0 else 0
        cap.release()
        logger.info(f"Video duration: {video_duration:.2f} seconds")

        # 4. AI selects the most engaging ~7s window
        clip_start = 0.0
        clip_duration = min(CLIP_TARGET_DURATION, video_duration)

        if video_duration > CLIP_TARGET_DURATION:
            logger.info("Video longer than 7s. Requesting AI to find the most engaging clip...")
            select_prompt = f"""
You are an expert social media video editor for YouTube Shorts.
Select the single most engaging, visually exciting, or viral ~{int(CLIP_TARGET_DURATION)} second continuous portion of this movie clip.
It must be the part that grabs attention instantly (action peak, surprising moment, iconic dialogue, dramatic twist).

Total Video Duration: {video_duration:.2f} seconds

Video Title: {title}
Channel: {channel}
Description: {description}

Timeline and Scene Analysis:
{json.dumps(scene_analysis[:30], indent=2)}

Transcript with Timestamps:
{raw_transcript[:2500]}

Return ONLY a valid JSON object with keys "start_time" and "duration" (seconds as floats).
The duration MUST be between 4.0 and {CLIP_MAX_DURATION} seconds (target ~{CLIP_TARGET_DURATION}s).
Also make sure start_time + duration <= total video duration.
Example response:
{{"start_time": 12.5, "duration": {CLIP_TARGET_DURATION}}}
Do not output any explanation or extra text.
"""
            try:
                llm_response = await run_llm(client, select_prompt, temperature=0.3, max_tokens=100)
                logger.info(f"AI clip selection response: {llm_response}")
                clean_json = llm_response.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_json)
                clip_start = float(data.get("start_time", 0.0))
                clip_duration = float(data.get("duration", CLIP_TARGET_DURATION))

                if clip_start < 0 or clip_start >= video_duration:
                    clip_start = 0.0
                if clip_duration < 4.0 or clip_duration > CLIP_MAX_DURATION:
                    clip_duration = CLIP_TARGET_DURATION
                if clip_start + clip_duration > video_duration:
                    clip_duration = max(4.0, video_duration - clip_start)
            except Exception as e:
                logger.warning(f"Failed to parse AI clip selection, defaulting to first {CLIP_TARGET_DURATION}s: {e}")
                clip_start = 0.0
                clip_duration = min(CLIP_TARGET_DURATION, video_duration)

        logger.info(f"Selected clip window: start={clip_start:.2f}s, duration={clip_duration:.2f}s")

        # 5. Cut the 7s clip
        os.makedirs("clips", exist_ok=True)
        clip_path = f"clips/{video_id}.mp4"
        logger.info("Cutting 7-second clip with FFmpeg...")
        cut_command = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", f"{clip_start:.3f}",
            "-t", f"{clip_duration:.3f}",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            clip_path
        ]
        subprocess.run(cut_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 6. Analyze the 7s clip (transcript, OCR, objects)
        logger.info("Analyzing the 7-second clip...")
        segments, info = await asyncio.to_thread(model.transcribe, clip_path, beam_size=5)
        clip_transcript = ""
        for segment in segments:
            clip_transcript += f"{segment.text} "
        clip_transcript = clip_transcript.strip() or "No dialogue detected in clip."

        clip_scene_list = await asyncio.to_thread(detect, clip_path, ContentDetector())
        clip_scene_analysis = [
            {"scene_num": i + 1, "start_time": s[0].get_seconds(), "end_time": s[1].get_seconds()}
            for i, s in enumerate(clip_scene_list)
        ]

        ocr_results = []
        objects_detected = set()
        yolo_model = YOLO('yolov8n.pt')
        reader = easyocr.Reader(['en'], gpu=False)

        best_conf = 0.0
        arrow_x = 0.5
        arrow_y = 0.5

        clip_cap = cv2.VideoCapture(clip_path)
        clip_fps = clip_cap.get(cv2.CAP_PROP_FPS)
        clip_frames = int(clip_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_times = [0.0]
        if clip_frames > 1:
            frame_times.append(clip_frames * 0.5 / clip_fps)
            frame_times.append((clip_frames - 1) / clip_fps)
        for t in frame_times:
            clip_cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * clip_fps))
            ret, frame = clip_cap.read()
            if not ret:
                continue
            try:
                text_results = reader.readtext(frame, detail=0)
                if text_results:
                    ocr_results.extend(text_results)
            except Exception:
                pass
            try:
                results = yolo_model(frame, verbose=False)
                for r in results:
                    for box in r.boxes:
                        conf = float(box.conf[0])
                        cls_idx = int(box.cls[0])
                        # Keep track of the most confident object for the red arrow highlight
                        if conf > best_conf:
                            best_conf = conf
                            coords = box.xyxyn[0].tolist()
                            arrow_x = (coords[0] + coords[2]) / 2.0
                            arrow_y = coords[1] # Point at top edge of the bounding box
                        objects_detected.add(yolo_model.names[cls_idx])
            except Exception:
                pass
        clip_cap.release()
        ocr_str = " | ".join(list(set(ocr_results))) if ocr_results else "None"
        objects_str = ", ".join(sorted(objects_detected)) if objects_detected else "None"

        # 7. Short summary of the clip
        summary_prompt = f"""
You are an AI video summarizer.
Write a short, clear summary (2-3 sentences) in English describing the actual events, actions, and settings shown in this 7-second movie clip.

Movie Title: {title}
Clip Dialogue Transcript: {clip_transcript}
OCR Text (visible on screen): {ocr_str}
Detected Objects: {objects_str}
"""
        try:
            clip_summary = await run_llm(client, summary_prompt, temperature=0.4, max_tokens=200)
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")
            clip_summary = "Summary generation failed."

        # 8. Generate interesting movie fact(s)
        logger.info("Generating interesting movie fact(s) with AI...")
        fact_prompt = f"""
Act as a viral pop culture and movie trivia creator for Instagram Reels/YouTube Shorts.
Generate 1 behind-the-scenes (BTS) fact for the movie/TV show: {title}.

Strictly follow this structure:
1. Hook: Start with "When filming [Movie Name] ([Release Year]), ..." (e.g. "When filming Spider-Man 2 (2004), ...").
2. Story: Describe an unscripted moment, accidental injury, actor's improvisation, or set secret in 30-40 simple words.
3. No Double Quotes: Do NOT use any double quotes " " anywhere in the fact text. If there is a quote from the actor/director, write it as normal text (e.g. Levy said they had to push Blender to its limits).
4. Bold Key Words: Bold the most dramatic/important keywords (especially in the statement or quote) by wrapping them in double asterisks (e.g. **accidentally**, **improvised**, **smashed**, **secret**, **idea**).
5. Word Limit: Total length of the fact MUST be strictly between 50 to 65 words.
6. Emojis: Include a relevant emoji or two at the very end of the paragraph (e.g. 💀, 🍎).

Movie Details to use:
Movie: {title}
Channel: {channel}
Video Description: {description}
Scene Summary: {clip_summary}
Clip Dialogue: {clip_transcript}

Output ONLY the raw fact paragraph text. Do not number it, do not add explanations, do not use double quotes " " at all, and do not add hashtags.
"""
        try:
            fact_text = await run_llm(client, fact_prompt, temperature=0.7, max_tokens=250)
            fact_text = fact_text.strip()
        except Exception as e:
            logger.warning(f"Fact generation failed: {e}")
            fact_text = ""

        logger.info(f"Generated fact(s):\n{fact_text}")

        # 9. Save results
        await async_update_memory(video_id, {
            "scene_analysis": json.dumps(scene_analysis),
            "transcript": raw_transcript,
            "summary": clip_summary,
            "ocr_text": ocr_str,
            "clip_start": clip_start,
            "clip_duration": clip_duration,
            "clip_path": clip_path,
            "clip_transcript": clip_transcript,
            "clip_scene_analysis": json.dumps(clip_scene_analysis),
            "fact_text": fact_text,
            "arrow_x": arrow_x,
            "arrow_y": arrow_y,
        })

        logger.success("Video analysis and fact generation complete.")

    except Exception as e:
        logger.error(f"Error during video analysis: {e}")
        await async_update_memory(video_id, {"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(analyze_video())
