import os
import shutil
import subprocess
from loguru import logger

rx_dir = r"C:\Users\admin\Documents\reaction charactor"
assets_dir = "assets"
exports_dir = "exports"

def run_batch():
    if not os.path.exists(rx_dir):
        logger.error(f"Directory not found: {rx_dir}")
        return

    files = [f for f in os.listdir(rx_dir) if f.endswith(".mp4")]
    logger.info(f"Found {len(files)} reaction character files for batch testing.")

    # Set environment variable to bypass dynamic selection in smart_editing_agent.py
    os.environ["BATCH_TEST"] = "True"

    for idx, filename in enumerate(files):
        src_path = os.path.join(rx_dir, filename)
        dest_path = os.path.join(assets_dir, "reaction.mp4")
        
        logger.info(f"[{idx+1}/{len(files)}] Testing reaction character: {filename}")
        
        # Copy to assets/reaction.mp4
        shutil.copy(src_path, dest_path)
        
        # Run smart editing agent
        res = subprocess.run(["python", "agents/smart_editing_agent.py"], capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"Failed editing for {filename}: {res.stderr}")
            continue

        # Run upload agent (which renames the final video to the SEO name)
        res_up = subprocess.run(["python", "agents/upload_agent.py"], capture_output=True, text=True)
        if res_up.returncode != 0:
            logger.error(f"Failed upload agent for {filename}: {res_up.stderr}")
            continue

        # Look in exports/ for the renamed output video and copy it with a test name
        # The upload agent outputs 'Renamed local video to: exports\dog_chases_bird.mp4' (or similar)
        # Let's check what is the current filename in memory or look at exports/dog_chases_bird.mp4
        seo_path = os.path.join(exports_dir, "dog_chases_bird.mp4")
        if os.path.exists(seo_path):
            clean_name = filename.replace(" ", "_").replace("(", "").replace(")", "")
            test_output_name = f"test_{clean_name}"
            test_output_path = os.path.join(exports_dir, test_output_name)
            shutil.copy(seo_path, test_output_path)
            logger.success(f"Successfully generated comparison output: {test_output_path}")
        else:
            logger.error(f"Could not find compiled output at {seo_path}")

if __name__ == "__main__":
    run_batch()
