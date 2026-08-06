#!/bin/bash

# API Keys and Config
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-}"

echo "=========================================="
echo "🎬 Starting Movie Clips & Facts Editing Pipeline"
echo "=========================================="

echo "[1/3] Running YouTube Downloader Agent..."
python3 agents/downloader_agent.py || { echo "Downloader failed"; exit 1; }

echo "[2/3] Running Video Analysis Agent (7s clip + facts, this might take a while)..."
python3 agents/video_analysis_agent.py || { echo "Analysis failed"; exit 1; }

echo "[3/3] Running Report Agent..."
python3 agents/report_agent.py || { echo "Report failed"; exit 1; }

echo "=========================================="
echo "✅ Done! Check the 'clips' folder for your 7-second clip."
echo "=========================================="
