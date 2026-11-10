FROM python:3.12-slim

# ffmpeg for rendering, fonts for the lettering, and nothing that needs a display
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /studio

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ghostlight/ ghostlight/
COPY web/ web/
COPY config.yaml .

ENV PYTHONUNBUFFERED=1

# Edge TTS needs a writable HOME for its certificate work
RUN useradd -m ghostlight && chown -R ghostlight:ghostlight /studio
USER ghostlight

VOLUME ["/studio/data", "/studio/secrets"]

EXPOSE 8787

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health')"

CMD ["python", "-m", "ghostlight", "serve", "--host", "0.0.0.0", "--port", "8787"]
