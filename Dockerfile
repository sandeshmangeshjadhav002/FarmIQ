# FarmIQ backend — Render (Docker runtime)
#
# Render builds this image from the repo root. It bundles the backend AND the
# sibling FarmIQ-rag folder so the backend's default ML/RAG paths
# (../FarmIQ-rag/...) resolve correctly inside the container:
#   /app/backend          <- working dir (matches "cd backend")
#   /app/FarmIQ-rag       <- ../FarmIQ-rag from the working dir
FROM python:3.12-slim

# Build toolchain for C extensions (bcrypt, pymupdf, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy both sibling folders, preserving the layout the backend expects.
COPY FarmIQ-rag /app/FarmIQ-rag
COPY backend /app/backend

WORKDIR /app/backend

# Install backend deps, then the RAG deps from the nested folder (per build.sh).
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r /app/FarmIQ-rag/FarmIQ-RAG/requirements.txt

ENV PYTHONUNBUFFERED=1

# Render routes traffic to this port (declared in render.yaml too).
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
