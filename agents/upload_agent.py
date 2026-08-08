import os
import sys
import json
import asyncio
from loguru import logger
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from memory_agent import async_get_latest_video_id, async_get_memory, async_update_memory
from dotenv import load_dotenv

load_dotenv()

def get_oauth_credentials():
    scopes = ['https://www.googleapis.com/auth/drive']
    
    # 1. Google Drive Service Account Fallback
    if os.path.exists("service_account.json"):
        logger.info("Loading Google Drive Service Account credentials from service_account.json...")
        try:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=scopes)
            return creds
        except Exception as e:
            logger.error(f"Failed to load service_account.json: {e}")

    token_str = os.environ.get("GDRIVE_OAUTH_TOKEN")
    
    if token_str:
        try:
            token_data = json.loads(token_str)
            if token_data.get("type") == "service_account":
                logger.info("Loading Google Drive Service Account from environment variable...")
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_info(token_data, scopes=scopes)
                return creds
            else:
                logger.info("Loading Google Drive OAuth credentials from environment variable...")
                creds = Credentials.from_authorized_user_info(token_data, scopes)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                return creds
        except Exception as e:
            logger.error(f"Failed to parse GDRIVE_OAUTH_TOKEN: {e}")
            
    # Local fallback
    if os.path.exists("token.json"):
        logger.info("Loading Google Drive OAuth credentials from token.json...")
        try:
            creds = Credentials.from_authorized_user_file("token.json", scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds
        except Exception as e:
            logger.error(f"Failed to load token.json: {e}")
            
    return None

from openai import OpenAI

async def upload_video():
    video_id = await async_get_latest_video_id()
    if not video_id:
        logger.warning("No video_id found in memory. Skipping upload cleanly.")
        sys.exit(0)
        
    memory = await async_get_memory(video_id)
    final_video = memory.final_video_path
    
    if not final_video:
        logger.error("Final video path not found in memory.")
        sys.exit(1)
        
    # Generate meaningful title filename using NVIDIA Nemotron LLM
    api_key = os.environ.get("NVIDIA_API_KEY", "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")
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key,
        timeout=15.0
    )
    
    # 1. Get the facts text from memory and extract first 10 words for Title and Filename
    fact_text = memory.fact_text or ""
    words = [w.strip().lower() for w in fact_text.split() if w.strip()]
    first_10_words = words[:10]
    
    raw_title = " ".join(first_10_words)
    res = "".join(c if c.isalnum() or c == " " else "" for c in raw_title).strip()
    res = "_".join(res.split())
    
    if not res:
        res = f"{video_id}_final"
        
    clean_filename = f"{res}.mp4"
    logger.info(f"Generated title and filename from first 10 words of facts: {clean_filename}")

    # Generate SEO Details based on the filename/title using LLM
    prompt = f"""Generate Search Engine Optimization (SEO) details for a movie facts video.
The video title and filename is: "{res.replace('_', ' ')}"
Video clip details:
Summary: {memory.summary}
Transcript: {memory.transcript}

Your output MUST be a JSON object containing exactly three keys:
1. "description": A highly engaging YouTube description (approx 150-200 words) using keywords related to the title.
2. "keywords": A list of 10 relevant keywords.
3. "tags": A comma-separated string of 10 relevant tags.

Output ONLY the raw JSON. Do not include any markdown format blocks or introductory text.
"""
    
    try:
        def query_llm():
            completion = client.chat.completions.create(
              model="meta/llama-3.1-70b-instruct",
              messages=[
                  {"role": "user", "content": prompt}
              ],
              temperature=0.3,
              max_tokens=400,
              stream=False
            )
            return completion.choices[0].message.content.strip()
        
        seo_response = await asyncio.to_thread(query_llm)
        if seo_response.startswith("```json"):
            seo_response = seo_response[7:]
        if seo_response.endswith("```"):
            seo_response = seo_response[:-3]
        seo_response = seo_response.strip()
        
        seo_data = json.loads(seo_response)
        
        await async_update_memory(video_id, {
            "youtube_title": res.replace('_', ' ').title(),
            "youtube_description": seo_data.get("description", ""),
            "youtube_keywords": ", ".join(seo_data.get("keywords", [])) if isinstance(seo_data.get("keywords"), list) else str(seo_data.get("keywords")),
            "youtube_tags": seo_data.get("tags", "")
        })
        logger.info("Successfully updated database memory with SEO Title, Description, Keywords, and Tags.")
    except Exception as e:
        logger.warning(f"Failed to generate SEO details, using default: {e}")
        
    # Rename local file to match the new filename
    new_video_path = os.path.join(os.path.dirname(final_video), clean_filename)
    try:
        if os.path.exists(final_video):
            os.rename(final_video, new_video_path)
            final_video = new_video_path
            await async_update_memory(video_id, {"final_video_path": final_video})
            logger.info(f"Renamed local video to: {final_video}")
    except Exception as e:
        logger.warning(f"Failed to rename local video: {e}")
        
    logger.info(f"Uploading video {final_video} to Google Drive...")
    
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    creds = get_oauth_credentials()
    
    if not creds:
        logger.warning("Google Drive OAuth credentials not found. Skipping upload.")
        await async_update_memory(video_id, {"google_drive_public_url": "https://drive.google.com/local-test-no-creds"})
        return
        
    try:
        def do_upload():
            service = build('drive', 'v3', credentials=creds)
            file_metadata = {'name': clean_filename}
            if folder_id:
                file_metadata['parents'] = [folder_id]
                
            media = MediaFileUpload(final_video, mimetype='video/mp4', resumable=True)
            
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            file_id = file.get('id')
            
            permission = {'type': 'anyone', 'role': 'reader'}
            service.permissions().create(fileId=file_id, body=permission).execute()
            
            file_metadata = service.files().get(fileId=file_id, fields='webViewLink').execute()
            return file_metadata.get('webViewLink')
            
        drive_url = await asyncio.to_thread(do_upload)
        
        await async_update_memory(video_id, {"google_drive_public_url": drive_url})
        logger.success(f"Video upload complete. URL: {drive_url}")
        
    except Exception as e:
        logger.error(f"Error during Google Drive upload: {e}")
        await async_update_memory(video_id, {
            "error": str(e),
            "google_drive_public_url": f"https://drive.google.com/error-fallback-local-{video_id}"
        })
        logger.warning("Continuing pipeline despite upload failure.")

if __name__ == "__main__":
    asyncio.run(upload_video())
