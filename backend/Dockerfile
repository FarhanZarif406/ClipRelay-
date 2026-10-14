FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp has to run YouTube's JavaScript to read a video. It needs Deno 2.3+ or Node.js 22+; Debian's own
# nodejs package is older than that, so yt-dlp ignored it. Deno is the runtime yt-dlp looks for first.
COPY --from=denoland/deno:bin-2.7.11 /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 cliprelay && mkdir -p /data/media && chown -R cliprelay /app /data
USER cliprelay

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
