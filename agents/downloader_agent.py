import os
import sys
import uuid
import json
import asyncio
import subprocess
from datetime import datetime, timezone
from loguru import logger
from memory_agent import async_update_memory

# Track downloaded videos locally and persist to git history.txt
HISTORY_FILE = "history.txt"
# File with one YouTube video/playlist URL per line (# = comment)
SOURCES_FILE = "sources.txt"


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_history(url: str):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")
    # Commit and push back to repository to persist state across workflow runs
    try:
        subprocess.run(["git", "config", "user.name", "Movie Facts Agent"], check=True)
        subprocess.run(["git", "config", "user.email", "agent@movie-facts.com"], check=True)
        subprocess.run(["git", "add", HISTORY_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"Track processed video: {url}"], check=True)

        if os.environ.get("GITHUB_ACTIONS") == "true":
            pat = os.environ.get("GH_TOKEN")
            if pat:
                repo = os.environ.get("GITHUB_REPOSITORY", "Vikram-Bosak/movie-clips-facts-edit-engine2")
                push_url = f"https://{pat}@github.com/{repo}.git"
                subprocess.run(["git", "push", push_url, "main"], check=True)
            else:
                subprocess.run(["git", "push", "origin", "main"], check=True)
            logger.info(f"Successfully committed and pushed {HISTORY_FILE} updates.")
        else:
            logger.info(f"Successfully committed {HISTORY_FILE} locally. Skipping git push in non-CI environment.")
    except Exception as e:
        logger.warning(f"Git commit/push for history tracking failed: {e}")


def load_sources():
    if not os.path.exists(SOURCES_FILE):
        logger.error(f"Sources file {SOURCES_FILE} not found.")
        return []
    urls = []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def get_cookie_flags() -> list:
    flags = []
    cookies_path = "cookies.txt"
    if os.path.exists(cookies_path):
        flags.extend(["--cookies", cookies_path])
    elif os.name == 'nt':
        try:
            flags.extend(["--cookies-from-browser", "chrome"])
        except Exception:
            try:
                flags.extend(["--cookies-from-browser", "edge"])
            except Exception:
                pass
    return flags


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _entry_url(e: dict, is_youtube: bool) -> str:
    """Build a usable download URL for a resolved entry."""
    url = e.get("webpage_url") or e.get("url") or e.get("original_url")
    if url and url.startswith("http"):
        return url
    if is_youtube:
        return canonical_url(e.get("id", ""))
    return None


async def resolve_entries(url: str):
    """Resolve a single video or playlist URL into a list of video entries."""
    cmd = ["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github", "--flat-playlist", "--skip-download", "-J"] + get_cookie_flags() + [url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"yt-dlp metadata failed for {url}: {stderr.decode()[:200]}")
            return []

        data = json.loads(stdout)
    except Exception as e:
        logger.warning(f"Error resolving {url}: {e}")
        return []

    extractor = (data.get("extractor_key") or "").lower()

    if data.get("_type") == "playlist":
        entries = data.get("entries", []) or []
        resolved = []
        for e in entries:
            is_youtube = "youtube" in (e.get("extractor_key") or "").lower()
            eurl = _entry_url(e, is_youtube)
            if not eurl:
                continue
            resolved.append({
                "url": eurl,
                "title": e.get("title"),
                "channel": e.get("uploader") or e.get("channel"),
                "duration": e.get("duration"),
                "upload_date": e.get("upload_date"),
                "timestamp": e.get("timestamp"),
            })
        logger.info(f"Resolved playlist '{data.get('title')}' with {len(resolved)} videos.")
        return resolved

    is_youtube = "youtube" in extractor
    video_id = data.get("id")
    if not video_id:
        logger.warning(f"Could not extract video id from {url}")
        return []
    eurl = data.get("webpage_url") or data.get("original_url")
    if not eurl or not eurl.startswith("http"):
        eurl = canonical_url(video_id) if is_youtube else url
    return [{
        "url": eurl,
        "title": data.get("title"),
        "channel": data.get("uploader") or data.get("channel"),
        "duration": data.get("duration"),
        "upload_date": data.get("upload_date"),
        "timestamp": data.get("timestamp"),
    }]


async def fetch_full_metadata(video_url: str):
    """Fetch full metadata (title, description, channel, duration) for a video."""
    cmd = ["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github", "--skip-download", "-J"] + get_cookie_flags() + [video_url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"Full metadata fetch failed for {video_url}")
            return {}
        return json.loads(stdout)
    except Exception as e:
        logger.warning(f"Error fetching full metadata: {e}")
        return {}


async def download_video():
    logger.info("Starting YouTube Movie Clip Downloader...")

    processed_urls = load_history()
    
    # Simplify search query to avoid parsing issues in yt-dlp URL scheme resolver
    studios_query = "movie clip compilation"
    search_url = f"ytsearchdate30:{studios_query}"
    logger.info(f"Searching YouTube with query: {studios_query}")
    
    search_results = await resolve_entries(search_url)
    if not search_results:
        logger.error("No search results returned from YouTube.")
        sys.exit(1)
        
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    
    hourly_candidates = []
    daily_candidates = []
    other_candidates = []
    skipped_already_processed = []
    
    for video in search_results:
        target_url = video["url"]
        if target_url in processed_urls:
            skipped_already_processed.append(video)
            continue
            
        # Check if uploader belongs to a major Hollywood studio
        studios = ["warner", "universal", "sony", "paramount", "disney", "marvel", "20th century", "lionsgate", "movieclips", "binge society"]
        channel_name = (video.get("channel") or "").lower()
        if not any(s in channel_name for s in studios):
            continue
            
        # Filter by duration under 240s (aligns with reference match-filter)
        dur = video.get("duration")
        if dur and float(dur) > 240:
            continue
            
        # Check if hourly (last 1 hour)
        is_hourly = False
        ts = video.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(ts, timezone.utc)
                if now - dt <= timedelta(hours=1):
                    is_hourly = True
            except Exception:
                pass
                
        # Check if daily (today)
        is_daily = False
        ud = video.get("upload_date")
        if ud:
            try:
                dt = datetime.strptime(ud, "%Y%m%d").replace(tzinfo=timezone.utc)
                if dt.date() == now.date():
                    is_daily = True
            except Exception:
                pass
                
        if is_hourly:
            hourly_candidates.append(video)
        elif is_daily:
            daily_candidates.append(video)
        else:
            other_candidates.append(video)
            
    # Priority Selection
    if hourly_candidates:
        candidates = hourly_candidates
        logger.info(f"Priority 1: Found {len(hourly_candidates)} clips uploaded in the last hour.")
    elif daily_candidates:
        candidates = daily_candidates
        logger.info(f"Priority 2: No hourly clips found. Found {len(daily_candidates)} clips uploaded today.")
    else:
        candidates = other_candidates
        logger.info(f"Priority 3: No daily clips found. Using {len(other_candidates)} recent clips.")
        
    if not candidates:
        logger.error("No unprocessed videos found matching search results.")
        sys.exit(1)

    os.makedirs("downloads", exist_ok=True)
    video_id = str(uuid.uuid4())
    output_path = f"downloads/{video_id}.mp4"

    failed_downloads = []
    for video in candidates:
        target_url = video["url"]
        logger.info(f"Attempting to download {target_url} - {video.get('title')}")

        command = [
            "yt-dlp",
            "--no-check-certificates",
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
            "--output", output_path,
            "--merge-output-format", "mp4",
            "--quiet",
        ] + get_cookie_flags() + [target_url]

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0 and os.path.exists(output_path):
                logger.success(f"Download successful! Video ID: {video_id}")

                save_history(target_url)

                metadata = await fetch_full_metadata(target_url)
                logger.info(f"Metadata: title='{metadata.get('title')}', channel='{metadata.get('uploader')}', duration={metadata.get('duration')}s")

                run_metrics = {
                    "downloaded": [{"url": target_url, "title": metadata.get("title") or video.get("title") or "Untitled"}],
                    "skipped": [{"url": x["url"], "title": x.get("title") or "Untitled", "reason": "Already processed in history"} for x in skipped_already_processed],
                    "failed": failed_downloads
                }

                await async_update_memory(video_id, {
                    "source_url": target_url,
                    "youtube_title": metadata.get("title") or video.get("title") or "Untitled",
                    "youtube_description": metadata.get("description") or "",
                    "youtube_channel": metadata.get("uploader") or video.get("channel") or "",
                    "source_duration": float(metadata.get("duration") or video.get("duration") or 0),
                    "local_video_path": output_path,
                    "start_time": datetime.now(timezone.utc).isoformat(),
                    "downloader_logs": json.dumps(run_metrics),
                    "github_repository": os.environ.get("GITHUB_REPOSITORY"),
                    "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                    "github_run_url": f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}" if os.environ.get("GITHUB_RUN_ID") else None
                })
                return
            else:
                err_msg = stderr.decode()[:200] or "Unknown download error"
                logger.warning(f"yt-dlp failed for {target_url}: {err_msg}. Trying next video...")
                failed_downloads.append({"url": target_url, "title": video.get("title") or "Untitled", "reason": f"yt-dlp failed: {err_msg}"})
                if os.path.exists(output_path):
                    os.remove(output_path)
        except Exception as e:
            logger.warning(f"Error executing yt-dlp: {e}")
            failed_downloads.append({"url": target_url, "title": video.get("title") or "Untitled", "reason": f"Exception: {e}"})

    logger.error("Failed to download any movie clip.")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(download_video())
