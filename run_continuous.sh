#!/bin/bash

# API Keys and Config
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-}"
export GOOGLE_SHEET_ID="1jT0jE0_uRAWHZdmP8cNpZXeaMWA-TKDg0Y-9r4R1e3o"

echo "=========================================="
echo "🔄 Starting Continuous 24/7 Editing Engine"
echo "=========================================="

while true; do
    echo "▶️ Starting new pipeline cycle..."
    
    python3 agents/downloader_agent.py
    DOWNLOAD_STATUS=$?
    
    if [ $DOWNLOAD_STATUS -eq 2 ]; then
        echo "📭 No new videos found in Google Sheet. Stopping the 24/7 loop."
        break
    elif [ $DOWNLOAD_STATUS -ne 0 ]; then
        echo "❌ Downloader failed with error. Retrying in 60 seconds..."
        sleep 60
        continue
    fi
    
    python3 agents/video_analysis_agent.py || { echo "Analysis failed"; sleep 60; continue; }
    python3 agents/smart_editing_agent.py || { echo "Smart Editing failed"; sleep 60; continue; }
    python3 agents/upload_agent.py || { echo "Upload failed"; sleep 60; continue; }
    python3 agents/report_agent.py || { echo "Report failed"; sleep 60; continue; }
    
    echo "✅ Finished one video! Moving to the next one immediately..."
    echo "------------------------------------------"
done

echo "✅ All videos from Google Sheet have been processed!"
