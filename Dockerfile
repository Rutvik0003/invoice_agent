# Stage 1: build the React frontend into frontend/dist
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with Tesseract OCR
FROM python:3.11-slim
# OMP_THREAD_LIMIT: OCR runs its passes as separate Tesseract processes; threads inside each only fight for the CPU
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_THREAD_LIMIT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY --chown=app:app backend/ backend/
COPY --chown=app:app data/ data/
COPY --from=frontend --chown=app:app /app/frontend/dist frontend/dist
# The app user must own backend/ so SQLite can create its database and journal files there
RUN chown app:app /app/backend

USER app
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
