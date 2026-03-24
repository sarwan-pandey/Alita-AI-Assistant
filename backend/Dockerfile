# ─────────────────────────────────────────────────────────────────────────────
# Aura Assistant — Backend Production Dockerfile
# Optimized for Railway / Render / any cloud platform
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System dependencies (ffmpeg for audio processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create data directories
RUN mkdir -p data/conversations data/reminders data/training models/whisper_cache

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "20", "--ws-ping-timeout", "30"]
