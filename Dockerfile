FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

ENV FRONTEND_DIST_DIR=/app/frontend/dist \
    DATA_DIR=/app/data \
    SQLITE_PATH=/app/data/slideforge.db \
    TEMPLATES_DIR=/app/data/templates \
    JOBS_DIR=/app/data/jobs

RUN apt-get update && apt-get install -y \
    libreoffice-impress \
    poppler-utils \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/
WORKDIR /app/backend
RUN pip install --no-cache-dir -e .
RUN npm ci --omit=dev
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

WORKDIR /app/backend
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
