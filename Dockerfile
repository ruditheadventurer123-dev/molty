# ═══════════════════════════════════════════════════════════════
# Molty Royale AI Agent Bot — Docker Image
# ═══════════════════════════════════════════════════════════════
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (for numpy/scipy build if needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY rss/ ./rss/

# Create data directories for runtime
RUN mkdir -p data/game_history data/models

# Environment variables (set defaults, override at runtime)
ENV MR_API_KEY=""
ENV MR_ROOM_TYPE="free"
ENV PYTHONUNBUFFERED=1

# Expose dashboard port (Railway uses PORT env var)
EXPOSE 8080

# Run the bot (multi_runner supports both single and multi-agent mode)
CMD ["python", "-m", "src.multi_runner"]
