FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libreoffice-impress \
    poppler-utils \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/
WORKDIR /app/backend
RUN pip install --no-cache-dir -e .

RUN npm install -g pptxgenjs react react-dom react-icons sharp
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

WORKDIR /app/backend
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
