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
    cmd = ["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github", "--flat-playlist", "--playlist-end", "30", "--skip-download", "-J"] + get_cookie_flags() + [url]
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

async def download_video():
    logger.info("Starting YouTube Movie Clip Downloader...")

    processed_urls = load_history()
    
    import urllib.parse
    import random
    
    # List of movies to search for targeted searches
    movies = [
        "The Dark Knight", "Inception", "Gladiator", "The Matrix", "Mad Max Fury Road", 
        "Inglourious Basterds", "Pulp Fiction", "Avengers Endgame", "Interstellar", 
        "Django Unchained", "Titanic", "Avatar", "Pirates of the Caribbean", "Terminator 2", 
        "John Wick", "Skyfall", "Mission Impossible", "The Lord of the Rings", "Jurassic Park", 
        "Die Hard", "Spider-Man", "Fight Club", "The Dark Knight Rises", "Logan", "No Country for Old Men"
    ]
    
    # Generic engaging search terms
    generic_terms = [
        "Best Hollywood action movie scenes",
        "Best fight scenes movie clips",
        "Hollywood movie dramatic scenes",
        "Best suspense movie clips",
        "Best funny movie scenes",
        "Hollywood chase scene",
        "Best emotional movie confrontation"
    ]
    
    # Randomly decide to search for a specific movie + scene type, or a generic term
    if random.choice([True, False]):
        movie = random.choice(movies)
        scene_type = random.choice([
            "fight scene", "action scene", "confrontation scene", 
            "suspense scene", "dramatic scene", "chase scene", "funny scene"
        ])
        studios_query = f"{movie} {scene_type} clip"
    else:
        studios_query = random.choice(generic_terms)
        
    encoded_query = urllib.parse.quote_plus(studios_query)
    # Search on YouTube (removed sp=CAI%3D to get relevant search results rather than just newest, which are often poor quality)
    search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
    logger.info(f"Searching YouTube with query: '{studios_query}' (URL: {search_url})")
    
    search_results = await resolve_entries(search_url)
    if not search_results:
        logger.error("No search results returned from YouTube.")
        sys.exit(1)
        
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    
    ranked_results = []
    skipped_already_processed = []
    
    for video in search_results:
        target_url = video["url"]
        if target_url in processed_urls:
            skipped_already_processed.append(video)
            continue
            
        # Strict Hollywood Filter: Skip Bollywood/Tollywood/Indian regional content
        indian_keywords = ["india", "bollywood", "tollywood", "kollywood", "hindi", "tamil", "telugu", "malayalam", "kannada", "punjabi", "bhojpuri"]
        title_lower = (video.get("title") or "").lower()
        channel_lower = (video.get("channel") or "").lower()
        description_lower = (video.get("description") or "").lower()
        
        is_indian = False
        for kw in indian_keywords:
            if kw in title_lower or kw in channel_lower or kw in description_lower:
                is_indian = True
                break
        if is_indian:
            logger.info(f"Skipping Indian/regional content: {video.get('title')} (Channel: {video.get('channel')})")
            continue
            
        # Filter by duration: standard clips, let's keep them under 300s (5 mins)
        dur = video.get("duration")
        if dur and float(dur) > 300:
            continue
            
        # Calculate source quality / channel score
        score = 0
        
        # Priority 1: Check uploader/channel name for official clip channels and major studios
        studios = [
            "movieclips", "joblo", "filmisnow", "kinocheck", "rottentomatoes", 
            "universalpictures", "warnerbros", "paramount", "sonyphotos", "marvel", 
            "a24", "neon", "netflix", "hbo", "disney", "lionsgate", "20thcentury"
        ]
        is_studio = any(s in channel_lower for s in studios)
        if is_studio:
            score += 150
            
        # Priority 2: Title keywords
        good_keywords = ["clip", "scene", "fight", "action", "confrontation", "suspense", "ending", "chase", "funny", "emotional"]
        for kw in good_keywords:
            if kw in title_lower:
                score += 10
                
        # Priority 3: HD quality indicator
        if "4k" in title_lower or "1080p" in title_lower or "hd" in title_lower:
            score += 15
            
        # Priority 4: Avoid bad uploader/title keywords (e.g. gameplay, reaction, walkthough, trailer)
        bad_keywords = ["reaction", "review", "trailer", "teaser", "parody", "shorts", "tiktok", "reels", "gameplay", "walkthrough", "analysis", "explained", "dubbed"]
        for kw in bad_keywords:
            if kw in title_lower or kw in channel_lower:
                score -= 60
                
        # Recency bonus if available
        ts = video.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(ts, timezone.utc)
                if now - dt <= timedelta(hours=24):
                    score += 10
            except Exception:
                pass
                
        video["priority_score"] = score
        ranked_results.append(video)
        
    # Sort candidates by score descending
    ranked_results.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
    candidates = ranked_results
    
    if candidates:
        logger.info(f"Top candidate: '{candidates[0].get('title')}' (Channel: '{candidates[0].get('channel')}', Score: {candidates[0].get('priority_score')})")
        
    if not candidates:
        logger.warning("No new, unprocessed videos found in search results. Skipping this run to prevent duplicate content.")
        sys.exit(0)

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
            "--match-filter", "duration <= 240",
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
