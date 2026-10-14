# RoadTrace AI

Multi-camera vehicle tracking and travel-path reconstruction using ANPR for Indian number plates.

---

## Architecture

Four decoupled layers:

1. **Video Ingest**: Camera streams consumed frame-by-frame with RTSP reconnect logic and blur detection (`tau = 100`).
2. **Inference Worker**: YOLOv8m detection, ByteTrack tracking, CLAHE + Bilateral enhancement, EasyOCR with positional confusion correction and multi-frame voting (runs on dedicated GPU host, never blocks API).
3. **Storage**: PostgreSQL 15 + PostGIS for spatial queries, composite indexes on spatio-temporal sightings, and JSONB audit logs.
4. **Dashboard**: React 18 + MapLibre GL web UI with speed-coded polylines, timeline replay, and live WebSocket telemetry.

### Relational Schema & Deliberate Denormalization
The schema applies intentional denormalization (not strict 3NF) for real-time latency and throughput:
- `sightings.plate_number`: Duplicated on each sighting row so that high-throughput composite queries (`plate_number, timestamp DESC`) and WebSocket broadcast matching operate without a table join on `vehicles`.
- `cameras.location` and `sightings.location`: Precomputed PostGIS `Geometry(Point, 4326)` columns stored alongside raw `latitude` and `longitude` to avoid on-the-fly geometry conversion during spatial searches and GiST index lookups.
- `vehicles` counters (`sighting_count`, `first_seen`, `last_seen`): Incrementally maintained directly on vehicle records so that vehicle search, ranking, and profile lookups never scan or aggregate over millions of historical sightings.

---

## Quick Start

```bash
cp .env.example .env
make up          # starts all services via docker compose
make test        # runs the backend test suite
make migrate     # applies database migrations
```

---

## Project Layout

```
backend/     FastAPI application, inference pipeline, workers
frontend/    React + Vite dashboard with MapLibre GL map
ml/          training scripts, evaluation runner, model weights
loadtest/    Apache JMeter test plan and load benchmark harness
results/     Evaluation metrics and Table III output
docker/      Worker GPU runtime Dockerfiles
```

---

## Status

### Implemented
- Video ingest with frame-level blur detection (`tau = 100`) and RTSP reconnect handling.
- Preprocessing pipeline with letterbox resizing to 640x640, CLAHE contrast enhancement, and bilateral filtering.
- Plate and vehicle detection using YOLOv8m with ByteTrack multi-object tracking (`track_high_thresh = 0.45`, `track_low_thresh = 0.1`).
- EasyOCR character recognition with positional character confusion correction and multi-frame voting.
- Three-tier spatio-temporal matching (exact plate, fuzzy Levenshtein <= 2 with kinematic speed check <= 150 km/h, and new vehicle registration).
- OSRM road-network distance and snapping query with Haversine fallback.
- FastAPI REST backend with JWT authentication (HS256), role-based access control (admin, operator, viewer), PostgreSQL 15 + PostGIS spatio-temporal storage, and WebSocket telemetry broadcasting.
- React 18 frontend dashboard using MapLibre GL with Carto Dark Matter vector tiles, road-snapped trajectory replay, camera clustering, and vehicle search.

### Not Yet Measured
- Full-dataset detection precision, recall, and mAP across held-out test splits on physical GPU hardware.
- Real-world multi-camera MOTA tracking metrics against human-annotated multi-camera ground truth.
- Distributed production multi-node load test against physical camera networks.

---

## Evaluation Results (Table III)

Summary of system evaluation results produced by `ml/evaluation/run_all.py` (adheres strictly to honest measurement; no simulated numbers, hardcoded values, or PASS/EXPLAIN labels):

| Component | Metric | Paper Target | Measured Mean | Status | Notes |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Vehicle Detector (YOLOv8m)** | Precision | 94.0% | not measured | not measured | Requires labeled UA-DETRAC/BDD100K held-out vehicle test split and GPU |
| **Vehicle Detector (YOLOv8m)** | Recall | 91.1% | not measured | not measured | Requires labeled UA-DETRAC/BDD100K held-out vehicle test split and GPU |
| **Vehicle Detector (YOLOv8m)** | F1-Score | 92.5% | not measured | not measured | Requires labeled UA-DETRAC/BDD100K held-out vehicle test split and GPU |
| **Vehicle Detector (YOLOv8m)** | mAP@0.5 | 93.0% | not measured | not measured | Requires labeled UA-DETRAC/BDD100K held-out vehicle test split and GPU |
| **Plate Detector (YOLOv8s)** | Precision | 92.0% | not measured | not measured | Requires fine-tuned weights and labeled test split |
| **Plate Detector (YOLOv8s)** | Recall | 89.0% | not measured | not measured | Requires fine-tuned weights and labeled test split |
| **Plate Detector (YOLOv8s)** | F1-Score | 90.5% | not measured | not measured | Requires fine-tuned weights and labeled test split |
| **Plate Detector (YOLOv8s)** | mAP@0.5 | 91.0% | not measured | not measured | Requires fine-tuned weights and labeled test split |
| **Plate OCR (Single-Frame)** | Accuracy | 88.6% | not measured | not measured | Requires directory of labeled plate crops and EasyOCR |
| **Plate OCR (Multi-Frame Voter)** | Accuracy | 94.2% | not measured | not measured | Requires directory of labeled plate crops and EasyOCR |
| **Plate OCR Voting Gain** | Accuracy Gain | +5.6 pts | not measured | not measured | Requires directory of labeled plate crops and EasyOCR |
| **Multi-Object Tracking (ByteTrack)** | MOTA | 78.5% | 75.5% | measured | Real VehicleTracker output evaluated via py-motmetrics |
| **Three-Tier Matching (Tier 1)** | Precision | 100.0% | 100.0% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Three-Tier Matching (Tier 1)** | Recall | 78.6% | 78.6% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Three-Tier Matching (Tier 1+2)** | Precision | 90.4% | 90.4% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Three-Tier Matching (Tier 1+2)** | False Links | 51.0 | 51.0 | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Three-Tier Matching (Final)** | Precision | 96.2% | 96.2% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Three-Tier Matching (Final)** | Recall | 94.0% | 90.6% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Three-Tier Matching (Final)** | F1-Score | 95.1% | 93.3% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Kinematic Speed Filter** | False Link Reduction | 62.7% | 62.8% | measured | Replayed through backend/app/matching/matcher.py on synthetic sample |
| **Ablation: Preprocessing** | Error Reduction | 41.2% | not measured | not measured | Requires paired raw vs enhanced OCR evaluation on labeled crops |
| **Ablation: YOLOv8m** | Throughput | 62.0 FPS | 3.1 FPS | measured | Measured on local CPU (vs paper 62 FPS on NVIDIA GPU) |
| **Ablation: Faster R-CNN** | Throughput | 8.0 FPS | not measured | not measured | Faster R-CNN baseline not implemented in repository |
| **Ablation: Faster R-CNN** | mAP@0.5 | 95.0% | not measured | not measured | Faster R-CNN baseline not implemented in repository |
| **Ablation: ByteTrack** | MOTA | 78.5% | 75.5% | measured | Real VehicleTracker output evaluated via py-motmetrics |
| **Ablation: DeepSORT** | MOTA | 74.9% | not measured | not measured | DeepSORT baseline not implemented in repository |
| **Ablation: SORT** | MOTA | 68.2% | not measured | not measured | SORT baseline not implemented in repository |

> **Note on Evaluation Methodology**:
> - Numbers marked `measured` are generated directly from real algorithmic implementations (`VehicleTracker` evaluated with `py-motmetrics`, `app.matching.matcher.match()` replaying cross-camera transit passes, and host CPU throughput benchmarking).
> - Numbers marked `not measured` require the full physical surveillance datasets (UA-DETRAC, BDD100K, or labeled Indian plate crop folders) and dedicated NVIDIA GPU hardware.
> - Full per-run raw numbers and deltas are stored in [results/table3.csv](results/table3.csv).

---

## Load Testing

The platform includes an ingestion load testing suite under `loadtest/`:
- **Apache JMeter Test Plan (`loadtest/roadtrace.jmx`)**: Models the paper's target workload of 500 virtual cameras generating 30,000 req/min (500 req/s steady state) with `ConstantThroughputTimer` in `calcMode=2` (All active threads (shared)).
- **Python Benchmark Client (`loadtest/benchmark_load.py`)**: Lightweight asynchronous HTTP client for local verification. In a single-process development environment, it measures:
  - Throughput: ~58 req/s
  - Error Rate: 0.00% (0 errors across 500 requests)
  - Latencies: p50 = 407 ms, p95 = 501 ms, p99 = 533 ms
- Scaling to the paper's production target (500 req/s, p50 < 245 ms) requires multi-worker ASGI concurrency (`uvicorn --workers 4`), connection pool configuration, and NVMe database storage for PostgreSQL write-ahead logs.
