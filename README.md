# RoadTrace AI

Multi-camera vehicle tracking and travel-path reconstruction using ANPR
for Indian number plates.

## Architecture

Four decoupled layers:

1. **Video ingest** – camera streams consumed frame-by-frame
2. **Inference worker** – YOLOv8 detection, ByteTrack tracking, EasyOCR
   plate reading (runs on GPU, never blocks the API)
3. **Storage** – PostgreSQL 15 + PostGIS for sightings, plates and travel paths
4. **Dashboard** – React + Leaflet web UI for search, replay and analytics

## Quick start

```bash
cp .env.example .env
make up          # starts all services via docker compose
make test        # runs the backend test suite
make migrate     # applies database migrations
```

## Requirements

- Docker and Docker Compose
- Python 3.10+ (for local development)
- Node 18+ (for frontend development)

## Project layout

```
backend/     FastAPI application, inference pipeline, workers
frontend/    React + Vite dashboard
ml/          training scripts, evaluation, model weights
loadtest/    load and stress test scripts
```
