FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    wget \
    git \
    fonts-noto-color-emoji \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy requirements file first for caching
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt && pip install -U yt-dlp

# Pre-cache AI Models (YOLOv8, Faster-Whisper, EasyOCR)
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" && \
    python -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')" && \
    python -c "import easyocr; easyocr.Reader(['en'], gpu=False)"
