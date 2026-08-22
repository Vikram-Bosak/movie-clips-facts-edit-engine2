import os
import sys
import uuid
import json
import asyncio
import subprocess
from datetime import datetime, timezone
from loguru import logger
from memory_agent import async_update_memory
from openai import OpenAI
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Track downloaded videos locally and persist to git history.txt
HISTORY_FILE = "history.txt"
# File with one YouTube video/playlist URL per line (# = comment)
SOURCES_FILE = "sources.txt"


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


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def get_sheets_service():
    scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    
    token_str = os.environ.get("GDRIVE_OAUTH_TOKEN")
    if token_str:
        try:
            token_data = json.loads(token_str)
            if token_data.get("type") == "service_account":
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_info(token_data, scopes=scopes)
                return build('sheets', 'v4', credentials=creds)
            else:
                from google.auth.transport.requests import Request
                creds = Credentials.from_authorized_user_info(token_data, scopes)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                return build('sheets', 'v4', credentials=creds)
        except Exception as e:
            logger.error(f"Failed to load credentials from GDRIVE_OAUTH_TOKEN: {e}")

    if os.path.exists('token.json'):
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file('token.json', scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('sheets', 'v4', credentials=creds)
    return None

def get_video_from_sheet(sheet_id, sheet_name=None):
    service = get_sheets_service()
    if not service:
        logger.warning("Google Sheets credentials not found. Ensure token.json exists.")
        return None
    
    try:
        sheet = service.spreadsheets()
        
        if not sheet_name:
            sheet_meta = sheet.get(spreadsheetId=sheet_id).execute()
            sheet_name = sheet_meta['sheets'][0]['properties']['title']
            
        result = sheet.values().get(spreadsheetId=sheet_id, range=sheet_name).execute()
        values = result.get('values', [])
        
        if not values:
            logger.info("No data found in Google Sheet.")
            return None
            
        headers = values[0]
        try:
            link_idx = headers.index("Video Link")
        except ValueError:
            link_idx = next((i for i, v in enumerate(headers) if "link" in v.lower()), -1)
            
        try:
            status_idx = headers.index("Status")
        except ValueError:
            status_idx = next((i for i, v in enumerate(headers) if "status" in v.lower()), -1)
            
        try:
            title_idx = headers.index("Video Title")
        except ValueError:
            title_idx = next((i for i, v in enumerate(headers) if "title" in v.lower()), -1)
            
        if link_idx == -1 or status_idx == -1:
            logger.error("Required columns 'Link' and 'Status' not found in Google Sheet.")
            return None
            
        for i, row in enumerate(values):
            if i == 0:
                continue
                
            status = row[status_idx] if len(row) > status_idx else ""
            if status != "Video Edited":
                link = row[link_idx] if len(row) > link_idx else ""
                title = row[title_idx] if title_idx != -1 and len(row) > title_idx else ""
                
                if link:
                    # Return 1-indexed row number for A1 notation update (header is row 1)
                    return {"url": link, "title": title, "row_index": i + 1, "status_col": chr(65 + status_idx)}
                    
        logger.info("All videos in Google Sheet are marked as 'Video Edited'.")
        return None
        
    except Exception as e:
        logger.error(f"Error accessing Google Sheets API: {e}")
        return None

def mark_video_as_edited(sheet_id, row_index, status_col_letter, sheet_name=None):
    service = get_sheets_service()
    if not service:
        return False
        
    try:
        sheet = service.spreadsheets()
        
        if not sheet_name:
            sheet_meta = sheet.get(spreadsheetId=sheet_id).execute()
            sheet_name = sheet_meta['sheets'][0]['properties']['title']
            
        range_name = f"{sheet_name}!{status_col_letter}{row_index}"
        body = {
            'values': [["Video Edited"]]
        }
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption="USER_ENTERED", body=body).execute()
        logger.success(f"Updated Google Sheet status to 'Video Edited' at {range_name}")
    except Exception as e:
        logger.error(f"Error updating Google Sheet: {e}")


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


def normalize_url(url: str) -> str:
    """Normalize YouTube URLs to their canonical form to prevent duplicates."""
    import urllib.parse
    if not url:
        return url
    if "youtube.com/watch" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if 'v' in qs:
            return f"https://www.youtube.com/watch?v={qs['v'][0]}"
    elif "youtu.be/" in url:
        parsed = urllib.parse.urlparse(url)
        video_id = parsed.path.lstrip('/')
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


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

    processed_urls = load_history()
    
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME")
    
    sheet_video = None
    if sheet_id:
        logger.info(f"GOOGLE_SHEET_ID is set. Checking Google Sheet for unedited videos...")
        sheet_video = get_video_from_sheet(sheet_id, sheet_name)
        
    failed_downloads = []
    skipped_already_processed = []
    candidates = []

    if sheet_video:
        logger.info(f"Found unedited video in Google Sheet: {sheet_video['title']} ({sheet_video['url']})")
        candidates = [{"url": sheet_video["url"], "title": sheet_video["title"], "is_from_sheet": True, "sheet_info": sheet_video}]
        
    if not candidates:
        logger.warning("No new, unedited videos found in Google Sheet. Exiting.")
        sys.exit(2)

    os.makedirs("downloads", exist_ok=True)
    video_id = str(uuid.uuid4())
    output_path = f"downloads/{video_id}.mp4"

    failed_downloads = []
    for video in candidates:
        target_url = video["url"]
        title = video.get("title")
        
        # Extract video ID
        vid = ""
        if "v=" in target_url:
            vid = target_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in target_url:
            vid = target_url.split("youtu.be/")[1].split("?")[0]
        
        output_path = f"downloads/{vid if vid else video_id}.mp4"
        
        logger.info(f"Attempting to download {target_url} - {title}")
        
        command = [
            "yt-dlp",
            "--no-check-certificates",
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--match-filter", "duration <= 600",
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
            
            success = (proc.returncode == 0 and os.path.exists(output_path))
            
            if not success and ("reloaded" in stderr.decode() or "Sign in" in stderr.decode()):
                logger.warning("Cookies might be expired or blocked. Retrying without cookies...")
                command_no_cookies = [
                    "yt-dlp",
                    "--no-check-certificates",
                    "--js-runtimes", "node",
                    "--remote-components", "ejs:github",
                    "--extractor-args", "youtube:player_client=default",
                    "--match-filter", "duration <= 600",
                    "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
                    "--output", output_path,
                    "--merge-output-format", "mp4",
                    "--quiet",
                ] + [target_url]
                
                proc = await asyncio.create_subprocess_exec(
                    *command_no_cookies,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                success = (proc.returncode == 0 and os.path.exists(output_path))

            if success:
                logger.info(f"Download successful! Video ID: {video_id}")

                save_history(target_url)

                metadata = await fetch_full_metadata(target_url)
                logger.info(f"Metadata: title='{metadata.get('title')}', channel='{metadata.get('uploader')}', duration={metadata.get('duration')}s")

                if video.get("is_from_sheet") and sheet_id:
                    mark_video_as_edited(sheet_id, video["sheet_info"]["row_index"], video["sheet_info"]["status_col"], sheet_name=sheet_name)

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


