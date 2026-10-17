# ClipRelay's cloud editor for Google Cloud Run. Built by deploy.ps1 / deploy.sh, which put the backend's
# app/services/media.py next to this file first, so the cloud edits exactly like the server does.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FONT_FILE=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf \
    RENDER_THREADS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY main.py .
RUN test -f app/services/media.py || (echo "app/services/media.py is missing: build with deploy.ps1 or deploy.sh" && exit 1)

RUN useradd --create-home --uid 1000 editor
USER editor
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
