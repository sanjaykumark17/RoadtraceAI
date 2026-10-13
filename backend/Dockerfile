# ==============================================================================
# RoadTrace AI Backend - Multi-stage Production Dockerfile
# Base: python:3.10-slim
# ==============================================================================

# Stage 1: Build virtualenv and dependencies
FROM python:3.10-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip wheel && \
    pip install --no-cache-dir -r requirements.txt


# Stage 2: Minimal runtime image
FROM python:3.10-slim AS runner

WORKDIR /app

# Install minimal runtime shared libraries and curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtualenv from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run as non-root user
RUN groupadd -g 1000 roadtrace && \
    useradd -u 1000 -g roadtrace -m -s /bin/bash roadtrace

# Copy application source code
COPY --chown=roadtrace:roadtrace . /app

USER roadtrace

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
