FROM python:3.12-slim

# Install ffmpeg and system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    psmisc \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
RUN pip install --no-cache-dir \
    aiohttp \
    jinja2 \
    requests

# Copy application files
COPY . /app

EXPOSE 8090

ENV PORT=8090 \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

CMD ["python3", "app.py"]
