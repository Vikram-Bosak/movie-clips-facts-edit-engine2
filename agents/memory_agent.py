import sqlite3
import json
import asyncio
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "memory.db"

class MemoryModel(BaseModel):
    video_id: str
    source_url: Optional[str] = None
    original_title: Optional[str] = None
    original_description: Optional[str] = None
    local_video_path: Optional[str] = None
    transcript: Optional[str] = None
    translation: Optional[str] = None
    summary: Optional[str] = None
    scene_analysis: Optional[str] = None  # JSON string
    ocr_text: Optional[str] = None
    generated_script: Optional[str] = None
    voiceover_file: Optional[str] = None
    final_video_path: Optional[str] = None
    google_drive_public_url: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    github_repository: Optional[str] = None
    github_run_id: Optional[str] = None
    github_run_url: Optional[str] = None
    crop_start: Optional[float] = None
    crop_duration: Optional[float] = None
    sound_effects: Optional[str] = None
    # --- New workflow fields (movie clips / facts) ---
    youtube_title: Optional[str] = None
    youtube_description: Optional[str] = None
    youtube_channel: Optional[str] = None
    source_duration: Optional[float] = None
    clip_start: Optional[float] = None
    clip_duration: Optional[float] = None
    clip_path: Optional[str] = None
    clip_transcript: Optional[str] = None
    clip_scene_analysis: Optional[str] = None  # JSON string
    fact_text: Optional[str] = None
    downloader_logs: Optional[str] = None
    youtube_tags: Optional[str] = None
    youtube_keywords: Optional[str] = None
    arrow_x: Optional[float] = None
    arrow_y: Optional[float] = None
    arrow_x_start: Optional[float] = None
    arrow_y_start: Optional[float] = None
    arrow_x_end: Optional[float] = None
    arrow_y_end: Optional[float] = None
    arrow_t_start: Optional[float] = None
    arrow_t_end: Optional[float] = None
    circle_x_start: Optional[float] = None
    circle_y_start: Optional[float] = None
    circle_x_end: Optional[float] = None
    circle_y_end: Optional[float] = None
    circle_t_start: Optional[float] = None
    circle_t_end: Optional[float] = None
    delogo_regions: Optional[str] = None
    error: Optional[str] = None

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS memory (
            video_id TEXT PRIMARY KEY,
            source_url TEXT,
            original_title TEXT,
            original_description TEXT,
            local_video_path TEXT,
            transcript TEXT,
            translation TEXT,
            summary TEXT,
            scene_analysis TEXT,
            ocr_text TEXT,
            generated_script TEXT,
            voiceover_file TEXT,
            final_video_path TEXT,
            google_drive_public_url TEXT,
            start_time TEXT,
            end_time TEXT,
            github_repository TEXT,
            github_run_id TEXT,
            github_run_url TEXT,
            crop_start REAL,
            crop_duration REAL,
            sound_effects TEXT,
            youtube_title TEXT,
            youtube_description TEXT,
            youtube_channel TEXT,
            source_duration REAL,
            clip_start REAL,
            clip_duration REAL,
            clip_path TEXT,
            clip_transcript TEXT,
            clip_scene_analysis TEXT,
            fact_text TEXT,
            downloader_logs TEXT,
            youtube_tags TEXT,
            youtube_keywords TEXT,
            arrow_x REAL,
            arrow_y REAL,
            arrow_x_start REAL,
            arrow_y_start REAL,
            arrow_x_end REAL,
            arrow_y_end REAL,
            arrow_t_start REAL,
            arrow_t_end REAL,
            circle_x_start REAL,
            circle_y_start REAL,
            circle_x_end REAL,
            circle_y_end REAL,
            circle_t_start REAL,
            circle_t_end REAL,
            delogo_regions TEXT,
            error TEXT
        )
    ''')
    
    # Safe migration function
    def add_col(col_name, col_type):
        try:
            c.execute(f"SELECT {col_name} FROM memory LIMIT 1")
        except sqlite3.OperationalError:
            try:
                c.execute(f"ALTER TABLE memory ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                logger.warning(f"Failed to add column {col_name}: {e}")

    add_col("downloader_logs", "TEXT")
    add_col("youtube_tags", "TEXT")
    add_col("youtube_keywords", "TEXT")
    add_col("arrow_x", "REAL")
    add_col("arrow_y", "REAL")
    add_col("arrow_x_start", "REAL")
    add_col("arrow_y_start", "REAL")
    add_col("arrow_x_end", "REAL")
    add_col("arrow_y_end", "REAL")
    add_col("arrow_t_start", "REAL")
    add_col("arrow_t_end", "REAL")
    add_col("circle_x_start", "REAL")
    add_col("circle_y_start", "REAL")
    add_col("circle_x_end", "REAL")
    add_col("circle_y_end", "REAL")
    add_col("circle_t_start", "REAL")
    add_col("circle_t_end", "REAL")
    add_col("delogo_regions", "TEXT")

    conn.commit()
    conn.close()
    logger.info("Database initialized.")

async def async_get_memory(video_id: str) -> Optional[MemoryModel]:
    def fetch():
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM memory WHERE video_id=?", (video_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return MemoryModel(**dict(row))
        return None
    return await asyncio.to_thread(fetch)

async def async_update_memory(video_id: str, updates: Dict[str, Any]):
    def update():
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Check if exists
        c.execute("SELECT video_id FROM memory WHERE video_id=?", (video_id,))
        exists = c.fetchone()
        
        if not exists:
            c.execute("INSERT INTO memory (video_id) VALUES (?)", (video_id,))
            
        for key, value in updates.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            c.execute(f"UPDATE memory SET {key} = ? WHERE video_id = ?", (value, video_id))
            
        conn.commit()
        conn.close()
        logger.info(f"Memory updated for {video_id}: {list(updates.keys())}")
        
    await asyncio.to_thread(update)

async def async_get_latest_video_id() -> Optional[str]:
    def fetch():
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT video_id FROM memory ORDER BY rowid DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row:
            return row[0]
        return None
    return await asyncio.to_thread(fetch)

# Initialize DB on import
init_db()
