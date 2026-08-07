import os
import sys
import asyncio
import httpx
from datetime import datetime
from loguru import logger
from memory_agent import async_get_latest_video_id, async_get_memory


def truncate_str(text, max_len=300):
    if not text:
        return "N/A"
    return text[:max_len] + "..." if len(text) > max_len else text


async def send_report():
    video_id = await async_get_latest_video_id()
    if not video_id:
        logger.error("No video_id found in memory.")
        sys.exit(1)

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
                "name": "📽️ 1. Movie Clip Info",
                "value": f"**Title:** {title}\n**Channel:** {channel}\n**Source:** [YouTube Link]({source_url})\n**Desc:** {desc}"
            },
            {
                "name": "🎞️ 2. Extracted Clip",
                "value": f"**Clip Window:** {clip_start:.2f}s → {clip_start + clip_duration:.2f}s ({clip_duration:.2f}s)"
            },
            {
                "name": "💡 3. Interesting Fact(s)",
                "value": f"```\n{fact}\n```"
            },
            {
                "name": "🧠 4. Clip Analysis",
                "value": f"**Summary:** {summary}\n**Clip Transcript:**\n```\n{transcript}\n```"
            },
            {
                "name": "⚙️ 5. Metrics & GitHub",
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
