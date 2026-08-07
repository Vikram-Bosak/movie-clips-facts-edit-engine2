import os
import sqlite3
import shutil
import subprocess
import time
from loguru import logger

rx_dir = r"C:\Users\admin\Documents\reaction charactor"
assets_dir = "assets"
exports_dir = "exports"

def get_latest_video_id():
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("SELECT video_id FROM memory ORDER BY rowid DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def safe_remove(path):
    if os.path.exists(path):
        for _ in range(5):
            try:
                os.remove(path)
                return True
            except Exception:
                time.sleep(1.0)
        return False
    return True

def run_batch():
    if not os.path.exists(rx_dir):
        logger.error(f"Directory not found: {rx_dir}")
        return

    files = [f for f in os.listdir(rx_dir) if f.endswith(".mp4")]
    logger.info(f"Found {len(files)} reaction character files for batch testing.")

    video_id = get_latest_video_id()
    if not video_id:
        logger.error("No video_id found in database memory.")
        return

    logger.info(f"Using latest video ID for testing: {video_id}")

    # Set environment variable to bypass dynamic selection in smart_editing_agent.py
    os.environ["BATCH_TEST"] = "True"

    for idx, filename in enumerate(files):
        src_path = os.path.join(rx_dir, filename)
        dest_path = os.path.join(assets_dir, "reaction.mp4")
        
        logger.info(f"[{idx+1}/{len(files)}] Testing reaction character: {filename}")
        
        # Add a short delay to let Windows release file handles from the previous subprocess
        time.sleep(2.0)
        
        # Copy to assets/reaction.mp4
        shutil.copy(src_path, dest_path)
        
        # Delete old final video and overlay png files using safe retries to bypass Windows locks
        raw_output_path = os.path.join(exports_dir, f"{video_id}_final.mp4")
        fact_png = os.path.join(exports_dir, f"{video_id}_fact.png")
        profile_png = os.path.join(exports_dir, f"{video_id}_profile.png")
        
        safe_remove(raw_output_path)
        safe_remove(fact_png)
        safe_remove(profile_png)
        
        # Run smart editing agent (compiles exports/{video_id}_final.mp4)
        res = subprocess.run(["python", "agents/smart_editing_agent.py"], capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"Failed editing for {filename}: {res.stderr}")
            continue

        # Copy the compiled output directly to the comparison test folder
        if os.path.exists(raw_output_path):
            clean_name = filename.replace(" ", "_").replace("(", "").replace(")", "")
            test_output_path = os.path.join(exports_dir, f"test_{clean_name}")
            shutil.copy(raw_output_path, test_output_path)
            logger.success(f"Successfully generated comparison output: {test_output_path}")
        else:
            logger.error(f"Could not find compiled output at {raw_output_path}")

if __name__ == "__main__":
    run_batch()
