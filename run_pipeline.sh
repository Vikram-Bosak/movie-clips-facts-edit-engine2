#!/bin/bash

# API Keys and Config
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-}"

echo "=========================================="
echo "🎬 Starting Movie Clips & Facts Editing Pipeline"
echo "=========================================="

echo "[1/4] Running YouTube Downloader Agent..."
python3 agents/downloader_agent.py || { echo "Downloader failed"; exit 1; }

echo "[2/4] Running Video Analysis Agent (7s clip + facts, this might take a while)..."
python3 agents/video_analysis_agent.py || { echo "Analysis failed"; exit 1; }

echo "[3/4] Running Smart Editing Agent (compose Shorts with space bg + facts + profile + reaction)..."
python3 agents/smart_editing_agent.py || { echo "Smart Editing failed"; exit 1; }

echo "[4/5] Running Google Drive Upload Agent..."
python3 agents/upload_agent.py || { echo "Upload failed"; exit 1; }

echo "[5/5] Running Report Agent..."
python3 agents/report_agent.py || { echo "Report failed"; exit 1; }

echo "=========================================="
echo "✅ Done! Check the 'exports' folder for your final video."
echo "=========================================="
