import os
import sys
import asyncio
import httpx
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv
from memory_agent import async_get_latest_video_id, async_get_memory

load_dotenv()


def truncate_str(text, max_len=300):
    if not text:
        return "N/A"
    return text[:max_len] + "..." if len(text) > max_len else text


async def send_report():
    video_id = await async_get_latest_video_id()
    if not video_id:
        logger.warning("No video_id found in memory. Skipping report cleanly.")
        sys.exit(0)

    memory = await async_get_memory(video_id)
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL not set. Skipping report.")
        return

    logger.info("Preparing detailed report for Discord...")

    duration_str = "N/A"
    if memory.start_time and memory.end_time:
        try:
            start_dt = datetime.fromisoformat(memory.start_time)
            end_dt = datetime.fromisoformat(memory.end_time)
            diff = end_dt - start_dt
            seconds = int(diff.total_seconds())
            mins, secs = divmod(seconds, 60)
            duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        except Exception as e:
            logger.warning(f"Failed to calculate duration: {e}")

    title = truncate_str(memory.youtube_title or memory.original_title, 100)
    desc = truncate_str(memory.youtube_description or memory.original_description, 150)
    channel = truncate_str(memory.youtube_channel, 80) or "N/A"
    summary = truncate_str(memory.summary, 250)
    fact = truncate_str(memory.fact_text, 400) or "N/A"
    transcript = truncate_str(memory.clip_transcript or memory.transcript, 300)
    source_url = memory.source_url or 'N/A'
    clip_start = memory.clip_start if memory.clip_start is not None else 0.0
    clip_duration = memory.clip_duration if memory.clip_duration is not None else 0.0
    drive_url = memory.google_drive_public_url or ''
    
    # Extract edited final filename
    edited_video_file = "N/A"
    if memory.final_video_path:
        edited_video_file = os.path.basename(memory.final_video_path)

    # Parse downloader logs
    import json
    downloader_summary = "No download logs found."
    if hasattr(memory, "downloader_logs") and memory.downloader_logs:
        try:
            logs = json.loads(memory.downloader_logs)
            downloaded = "\n".join([f"• [{d['title']}]({d['url']})" for d in logs.get("downloaded", [])]) or "None"
            failed = "\n".join([f"• [{f['title']}]({f['url']}) (Reason: {f['reason']})" for f in logs.get("failed", [])]) or "None"
            skipped_list = logs.get("skipped", [])
            skipped = f"{len(skipped_list)} video(s) skipped (already processed in history)."
            if skipped_list:
                skipped += "\n" + "\n".join([f"  - {s['title']} ({s['url']})" for s in skipped_list[:3]])
                if len(skipped_list) > 3:
                    skipped += f"\n  - ... and {len(skipped_list) - 3} more"
            
            downloader_summary = f"**Downloaded:**\n{downloaded}\n\n**Failed/Rejected:**\n{failed}\n\n**Skipped:**\n{skipped}"
        except Exception as e:
            downloader_summary = f"Error parsing download logs: {e}"

    has_failed = memory.error is not None and memory.error != ""
    if has_failed:
        embed_title = "❌ Movie Clips & Facts Pipeline Failed!"
        embed_desc = f"The pipeline encountered an error: **{truncate_str(memory.error, 300)}**"
        embed_color = 15158332  # Red
    else:
        embed_title = "🚀 Movie Clips & Facts Pipeline Completed!"
        embed_desc = "The 7-second clip pipeline has finished executing successfully."
        embed_color = 5763719  # Green

    embed = {
        "title": embed_title,
        "description": embed_desc,
        "color": embed_color,
        "fields": [
            {
                "name": "📥 1. Downloader & Rejection Logs",
                "value": downloader_summary
            },
            {
                "name": "📽️ 2. Movie Clip Info",
                "value": f"**Title:** {title}\n**Channel:** {channel}\n**Source:** [YouTube Link]({source_url})\n**Desc:** {desc}"
            },
            {
                "name": "🎞️ 3. Extracted & Edited Clip",
                "value": f"**File:** `{edited_video_file}`\n**Clip Window:** {clip_start:.2f}s → {clip_start + clip_duration:.2f}s ({clip_duration:.2f}s)"
            },
            {
                "name": "💡 4. Interesting Fact(s)",
                "value": f"```\n{fact}\n```"
            },
            {
                "name": "🧠 5. Clip Analysis",
                "value": f"**Summary:** {summary}\n**Clip Transcript:**\n```\n{transcript}\n```"
            },
            {
                "name": "🔍 6. YouTube SEO Metadata",
                "value": f"**SEO Title:** {memory.youtube_title or 'N/A'}\n**Description:** {truncate_str(memory.youtube_description, 200)}\n**Keywords:** {truncate_str(memory.youtube_keywords, 150)}\n**Tags:** {truncate_str(memory.youtube_tags, 150)}"
            },
            {
                "name": "⚙️ 7. Metrics & GitHub",
                "value": f"**Time:** {duration_str}\n**Run:** [GitHub Action Run]({memory.github_run_url or 'https://github.com'})" + (f"\n**Drive Link:** [Google Drive Link]({drive_url})" if drive_url else "")
            }
        ],
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "footer": {
            "text": f"Run ID: {memory.github_run_id or 'N/A'}"
        }
    }

    payload = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
        logger.success("Detailed embed report sent to Discord successfully.")
    except Exception as e:
        logger.error(f"Error sending report to Discord: {e}")
        logger.warning("Continuing despite Discord reporting failure.")


if __name__ == "__main__":
    asyncio.run(send_report())
