# RoadTrace AI — Production Deployment Guide

This document details the production architecture, hosting topologies, environment variables, security hardening, and deployment procedures for the **RoadTrace AI** platform.

---

## 1. Production Architecture Overview

The RoadTrace AI production deployment follows a decoupled, cloud-native architecture:

```
                      ┌───────────────────────────────────────┐
                      │            End Users (Web)            │
                      └──────────────────┬────────────────────┘
                                         │ HTTPS
                                         ▼
                      ┌───────────────────────────────────────┐
                      │          Frontend on Vercel           │
                      │     (React 18 + Vite + Tailwind)      │
                      └──────────┬─────────────────┬──────────┘
                         HTTPS   │                 │  WSS (Live Feed)
                                 ▼                 ▼
                      ┌───────────────────────────────────────┐
                      │           API on Render               │
                      │   (FastAPI + Uvicorn Async Cluster)   │
                      └──────────┬─────────────────┬──────────┘
                         SQL/TCP │ (TLS)           │ LISTEN/NOTIFY (TLS)
                                 ▼                 │
     ┌─────────────────────────────────────────┐   │
     │      PostgreSQL + PostGIS on AWS RDS    │◄──┘
     │   (Spatial Indexes + JSONB Audit Logs)  │
     └───────────────────▲─────────────────────┘
                         │
                         │ SQL/TCP (TLS)
                         │
     ┌───────────────────┴─────────────────────┐
     │       GPU Worker on Dedicated Host      │
     │     (AWS EC2 g4dn / RunPod / Lambda)    │
     │  - YOLOv8m (Vehicle & Plate Detection)  │
     │  - EasyOCR + CLAHE + Multi-Frame Vote   │
     │  - ByteTrack MOT Tracking               │
     └─────────────────────────────────────────┘
```

---

## 2. PostgreSQL + PostGIS on AWS RDS

### 2.1 RDS Provisioning
* **Engine**: PostgreSQL 15.4 or 16.1.
* **Instance Class**: `db.t4g.medium` (development/staging) or `db.m6g.xlarge` (production).
* **Storage**: Provisioned IOPS SSD (`io2` or `gp3`), minimum 100 GB.
* **Parameter Group**:
  - `rds.force_ssl = 1` (forces TLS encryption in transit).
  - `shared_preload_libraries = 'postgis'`

### 2.2 PostGIS Initialization
Connect as the RDS master user and execute the extension bootstrap commands:

```sql
-- Connect via psql:
-- psql -h <rds-endpoint>.rds.amazonaws.com -U roadtrace -d roadtrace -p 5432

-- Enable PostGIS spatial engine:
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Verify PostGIS installation:
SELECT postgis_version(), postgis_full_version();
```

### 2.3 Database Migration & Seeding
Execute database migrations using Alembic from the backend:

```bash
# Set connection string to RDS endpoint
export RT_DATABASE_URL="postgresql+asyncpg://<user>:<password>@<rds-endpoint>:5432/roadtrace?ssl=require"
export RT_DATABASE_URL_SYNC="postgresql+psycopg2://<user>:<password>@<rds-endpoint>:5432/roadtrace?ssl=require"

# Run schema migrations to HEAD
alembic upgrade head

# Seed initial admin user and baseline camera fixtures
python -m app.db.seed
```

---

## 3. Backend API on Render

### 3.1 Render Web Service Configuration
* **Service Type**: Web Service (Docker or Python Native).
* **Environment**: Docker (uses [`backend/Dockerfile`](file:///d:/Roadtrace_AI/backend/Dockerfile)) or Python 3.10.
* **Region**: Choose region closest to your AWS RDS instance (e.g., `us-east-1` / `oregon`).
* **Start Command** (if native):
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4 --loop uvloop --http httptools
  ```
* **Health Check Path**: `/health`

### 3.2 Environment Variables (Render Dashboard)
| Variable | Value / Description | Sensitive |
| :--- | :--- | :--- |
| `RT_DATABASE_URL` | `postgresql+asyncpg://<user>:<pwd>@<rds-host>:5432/roadtrace?ssl=require` | Yes |
| `RT_DATABASE_URL_SYNC` | `postgresql+psycopg2://<user>:<pwd>@<rds-host>:5432/roadtrace?ssl=require` | Yes |
| `RT_SECRET_KEY` | High-entropy 64-character random string (e.g. `openssl rand -hex 32`) | Yes |
| `RT_CORS_ORIGINS` | `https://roadtrace.vercel.app,https://roadtrace.ai` | No |
| `RT_AUTH_RATE_LIMIT_PER_MINUTE` | `30` (throttles auth endpoints to prevent brute-force attacks) | No |
| `RT_AUTH_RATE_LIMIT_ENABLED` | `true` | No |
| `PYTHONUNBUFFERED` | `1` | No |

---

## 4. Frontend on Vercel

### 4.1 Vercel Project Setup
1. Import repository on [Vercel](https://vercel.com).
2. Configure **Root Directory**: `frontend`
3. Framework Preset: **Vite**
4. Build Command: `npm run build`
5. Output Directory: `dist`

### 4.2 Environment Variables (Vercel Project Settings)
| Variable | Value | Description |
| :--- | :--- | :--- |
| `VITE_API_URL` | `https://api.roadtrace.ai` | Base URL for REST endpoints |
| `VITE_WS_URL` | `wss://api.roadtrace.ai` | Secure WebSocket endpoint for live camera sighting feed |

### 4.3 Vercel SPA Routing Configuration (`frontend/vercel.json`)
```json
{
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Frame-Options", "value": "SAMEORIGIN" },
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" }
      ]
    }
  ]
}
```

---

## 5. GPU Worker on Dedicated GPU Host

The background inference worker requires CUDA acceleration to process YOLOv8m vehicle detection, plate localization, and EasyOCR recognition in real-time.

### 5.1 Host Specifications
* **Recommended Cloud Instances**:
  - AWS EC2: `g4dn.xlarge` (1x NVIDIA T4, 16 GB VRAM, 4 vCPUs, 16 GB RAM).
  - AWS EC2: `g5.xlarge` (1x NVIDIA A10G, 24 GB VRAM).
  - RunPod / Lambda Labs: 1x RTX 4090 or A4000.
* **OS**: Ubuntu 22.04 LTS with NVIDIA drivers (>= 535) and NVIDIA Container Toolkit.

### 5.2 Host Setup & Driver Verification
```bash
# Verify NVIDIA driver and CUDA availability
nvidia-smi

# Install NVIDIA Container Toolkit
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Test CUDA in Docker
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 5.3 Weight Mounting & Worker Deployment
Weights and models are pre-cached on host disk or mounted via Amazon S3 / EFS to prevent redownload cycles on boot:

```bash
# 1. Create weights directory on host
sudo mkdir -p /opt/roadtrace/weights /opt/roadtrace/snapshots
sudo chown -R 1000:1000 /opt/roadtrace

# 2. Download / copy YOLOv8 weights
aws s3 cp s3://roadtrace-weights/yolov8m.pt /opt/roadtrace/weights/yolov8m.pt
aws s3 cp s3://roadtrace-weights/plate_yolov8s.pt /opt/roadtrace/weights/plate_yolov8s.pt

# 3. Launch container with GPU allocation
docker run -d \
  --name roadtrace-gpu-worker \
  --restart always \
  --gpus all \
  --env RT_DATABASE_URL="postgresql+asyncpg://roadtrace:pwd@<rds-endpoint>:5432/roadtrace?ssl=require" \
  --env RT_DATABASE_URL_SYNC="postgresql+psycopg2://roadtrace:pwd@<rds-endpoint>:5432/roadtrace?ssl=require" \
  --env RT_YOLO_WEIGHTS="/app/weights/yolov8m.pt" \
  --env RT_WORKER_CONCURRENCY=2 \
  -v /opt/roadtrace/weights:/app/weights:ro \
  -v /opt/roadtrace/snapshots:/app/snapshots:rw \
  roadtrace-worker:latest
```

---

## 6. Security Hardening & Production Checklist

1. **Strict Origin CORS Policy**:
   - The backend restricts cross-origin resource sharing specifically to the verified Vercel frontend domains via `RT_CORS_ORIGINS`.
   - Wildcard (`*`) origins are rejected in production mode.

2. **Authentication Rate Limiting**:
   - `/api/v1/auth/login` and `/api/v1/auth/refresh` endpoints enforce IP-based sliding-window rate limiting (`RT_AUTH_RATE_LIMIT_PER_MINUTE=30`).
   - Requests exceeding thresholds trigger HTTP `429 Too Many Requests` with `Retry-After: 60`.
   - Reverse proxy client IP resolution inspects `X-Forwarded-For` headers safely.

3. **End-to-End TLS / HTTPS**:
   - Frontend: Vercel automated SSL certificates with HTTP Strict Transport Security (HSTS).
   - API: Render automated TLS certificate termination with mandatory HTTP-to-HTTPS redirect.
   - RDS: Forced TLS connection via `ssl=require` query parameters.

4. **Secrets Management**:
   - No plaintext passwords, database URLs, or JWT secrets are stored in Git.
   - All runtime secrets are passed strictly via cloud provider environment vaults (Vercel Project Settings, Render Secret Store, AWS Secrets Manager).

5. **Non-Root Container Sandboxing**:
   - Both backend and worker Dockerfiles execute under dedicated system user `roadtrace` (`UID 1000`) rather than `root`.
