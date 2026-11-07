# Single-container build: the API also serves the built web app on port 8000.
# Used for Azure App Service (see DEPLOY.md) and for `docker compose up` locally.

# ---- web app
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- API + web app
FROM python:3.12-slim
# espeak-ng gives the solution videos a spoken voice on Linux (Windows uses its built-in voices).
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
WORKDIR /app/backend
# Data (database, uploads, generated documents and videos). On Azure App Service /home is persistent storage.
ENV RF_DATA_DIR=/home/data SQLITE_JOURNAL_MODE=DELETE
EXPOSE 8000
# --proxy-headers: Azure terminates HTTPS in front of the container.
# app.tools.startup first: database check / repair, and the one-time copy into PostgreSQL. It never blocks start-up.
CMD ["sh", "-c", "python -m app.tools.startup; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
