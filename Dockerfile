# CloudClean on one address: web app + API + background worker in one
# container. Used for free hosting (Hugging Face Spaces, a free VM, or your own
# PC). Local development keeps using docker-compose.yml (three containers).
#
#   docker build -t cloudclean .
#   docker run -p 8000:8000 -v cloudclean_data:/app/data --env-file .env cloudclean
#
# Set PUBLIC_URL to the https address people open (see DEPLOY.md).

# ---- 1. build the web app -------------------------------------------------
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# A production build calls the API on the same address that served the page.
RUN npm run build

# ---- 2. the API, worker and built web app --------------------------------
FROM python:3.12-slim

# libjpeg/zlib for Pillow, qpdf for pikepdf, ffmpeg (+ ffprobe) for videos
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g qpdf ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Hosts like Hugging Face run the container as user 1000; it owns /app so the
# database and the secret key in /app/data can be written.
RUN useradd --create-home --uid 1000 cloudclean
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY --from=web /web/dist ./static
COPY docker/start.sh /usr/local/bin/cloudclean-start
RUN chmod +x /usr/local/bin/cloudclean-start \
    && mkdir -p /app/data && chown -R cloudclean:cloudclean /app

USER cloudclean
ENV STATIC_DIR=/app/static \
    PORT=8000 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["cloudclean-start"]
