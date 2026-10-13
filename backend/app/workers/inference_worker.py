"""Inference worker running as a dedicated background process/container.

Performs:
 1. Polls processing_jobs WHERE status='queued' using SELECT ... FOR UPDATE SKIP LOCKED;
    sets status='running'.
 2. Per job: FrameSource -> vehicle detection + ByteTrack -> plate crop + OCR -> PlateVoter.
 3. When a track's vote is finalized, emits exactly ONE sighting:
    plate_number, camera_id, UTC timestamp of the best frame, camera lat/lon,
    vehicle_class, ocr_confidence, frames_voted, snapshot JPG saved to disk.
    Then calls matching_service.ingest_sighting().
 4. Enforces no duplicate sightings per track_id.
 5. Updates frames_processed; finishes with status done or failed (+ error text).
 6. Preloads all model weights once at worker start.
 7. Provides graceful shutdown, structured logging, and concurrency control.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
from typing import Any, Dict, Optional, Set

import cv2
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.config import settings
from app.db.session import AsyncSession
from app.inference.detector import get_detector
from app.inference.ingest import FrameSource
from app.inference.plate_ocr import (
    OCRReaderSingleton,
    PlateDetectorSingleton,
    PlateVoter,
    VoteResult,
    process_vehicle_crop_for_plate,
)
from app.inference.tracker import VehicleTracker
from app.models.camera import Camera
from app.models.enums import JobStatus, VehicleClass
from app.models.processing_job import ProcessingJob
from app.models.sighting import Sighting
from app.models.vehicle import Vehicle
from app.services.matching_service import matching_service

# Structured logger setup
logger = logging.getLogger("roadtrace.worker")


def log_event(level: int, event: str, **kwargs: Any) -> None:
    """Output structured key-value log record."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **kwargs,
    }
    logger.log(level, json.dumps(payload, default=str))


_MODELS_PRELOADED = False


def load_all_models() -> Dict[str, Any]:
    """Preload all model weights once per worker process."""
    global _MODELS_PRELOADED
    log_event(logging.INFO, "models_preloading_started")

    # 1. Vehicle detector (YOLOv8m)
    detector = get_detector()

    # 2. Plate detector (YOLOv8s)
    plate_detector = PlateDetectorSingleton().model

    # 3. EasyOCR Reader (GPU if available)
    ocr_reader = OCRReaderSingleton().reader

    _MODELS_PRELOADED = True
    log_event(
        logging.INFO,
        "models_preloading_finished",
        models=["yolov8m", "plate_yolov8s", "easyocr"],
    )
    return {
        "detector": detector,
        "plate_detector": plate_detector,
        "ocr_reader": ocr_reader,
    }


async def claim_next_job(session: SAAsyncSession) -> Optional[ProcessingJob]:
    """Poll for the next queued job using SELECT ... FOR UPDATE SKIP LOCKED.

    Returns the claimed job with status set to 'running', or None if no queued jobs.
    """
    stmt = (
        select(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.queued)
        .order_by(ProcessingJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    res = await session.execute(stmt)
    job = res.scalar_one_or_none()
    if job:
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(job)
    return job


async def emit_sighting(
    track_id: int,
    vote_result: VoteResult,
    track_meta: Dict[str, Any],
    job: ProcessingJob,
    camera: Camera,
    session: SAAsyncSession,
    emitted_tracks: Set[int],
) -> Optional[Sighting]:
    """Emit exactly one sighting for a finalized track and persist snapshot JPG."""
    if track_id in emitted_tracks:
        return None
    emitted_tracks.add(track_id)

    # Check database to prevent any duplicate across restarts
    existing_stmt = (
        select(Sighting)
        .where(Sighting.job_id == job.id, Sighting.track_id == track_id)
        .limit(1)
    )
    existing_res = await session.execute(existing_stmt)
    if existing_res.scalar_one_or_none() is not None:
        log_event(
            logging.WARNING,
            "duplicate_sighting_suppressed",
            job_id=job.id,
            track_id=track_id,
        )
        return None

    # UTC timestamp of the best frame
    best_ts = track_meta.get("best_ts")
    if best_ts is None:
        best_ts = datetime.now(timezone.utc)
    elif best_ts.tzinfo is None:
        best_ts = best_ts.replace(tzinfo=timezone.utc)
    else:
        best_ts = best_ts.astimezone(timezone.utc)

    plate_number = vote_result.plate_number
    vehicle_class = track_meta.get("vehicle_class", VehicleClass.passenger_car)

    # Save snapshot JPG to disk
    snapshot_path: Optional[str] = None
    best_frame = track_meta.get("best_frame")
    if best_frame is not None:
        snapshots_dir = Path(settings.snapshots_dir)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        ts_sec = int(best_ts.timestamp())
        filename = f"job_{job.id}_cam_{job.camera_id}_track_{track_id}_{ts_sec}.jpg"
        full_disk_path = snapshots_dir / filename
        cv2.imwrite(str(full_disk_path), best_frame)
        snapshot_path = str(full_disk_path)

    # Ensure Vehicle entity exists or update last_seen
    v_stmt = select(Vehicle).where(Vehicle.plate_number == plate_number)
    v_res = await session.execute(v_stmt)
    vehicle = v_res.scalar_one_or_none()
    if vehicle is not None:
        vehicle.last_seen = best_ts
        vehicle.sighting_count += 1
    else:
        vehicle = Vehicle(
            plate_number=plate_number,
            vehicle_class=vehicle_class,
            first_seen=best_ts,
            last_seen=best_ts,
            sighting_count=1,
        )
        session.add(vehicle)
        await session.flush()

    # Geometry point from camera latitude and longitude
    location_elem = WKTElement(
        f"POINT({camera.longitude} {camera.latitude})", srid=4326
    )

    # OCR confidence: average confidence of winning plate or total / voted
    winning_conf_avg = (
        vote_result.total_confidence / vote_result.frames_voted
        if vote_result.frames_voted > 0
        else track_meta.get("best_conf", 0.0)
    )

    sighting = Sighting(
        vehicle_id=vehicle.id,
        camera_id=job.camera_id,
        plate_number=plate_number,
        raw_plate_text=plate_number,
        ocr_confidence=float(winning_conf_avg),
        vehicle_class=vehicle_class,
        track_id=track_id,
        timestamp=best_ts,
        location=location_elem,
        frames_voted=vote_result.frames_voted,
        snapshot_path=snapshot_path,
        job_id=job.id,
    )
    session.add(sighting)
    await session.commit()
    await session.refresh(sighting)

    log_event(
        logging.INFO,
        "sighting_emitted",
        sighting_id=sighting.id,
        job_id=job.id,
        track_id=track_id,
        plate_number=plate_number,
        vehicle_class=vehicle_class.value,
        ocr_confidence=round(sighting.ocr_confidence, 4),
        frames_voted=vote_result.frames_voted,
        timestamp=best_ts.isoformat(),
        snapshot_path=snapshot_path,
    )

    # Call matching service ingest stub
    await matching_service.ingest_sighting(sighting, db=session)

    return sighting


async def process_job(
    job_id: int,
    session: SAAsyncSession,
    models: Optional[Dict[str, Any]] = None,
) -> None:
    """Execute complete video inference pipeline for a single job."""
    job = await session.get(ProcessingJob, job_id)
    if not job:
        log_event(logging.ERROR, "job_not_found", job_id=job_id)
        return

    camera = await session.get(Camera, job.camera_id)
    if not camera:
        job.status = JobStatus.failed
        job.error = f"Camera {job.camera_id} not found"
        job.finished_at = datetime.now(timezone.utc)
        await session.commit()
        log_event(logging.ERROR, "camera_not_found", job_id=job_id, camera_id=job.camera_id)
        return

    log_event(
        logging.INFO,
        "job_processing_started",
        job_id=job.id,
        camera_id=job.camera_id,
        source_uri=job.source_uri,
    )

    # Load models if not already passed or preloaded
    if models is None:
        models = load_all_models()
    detector = models["detector"]
    plate_detector = models["plate_detector"]
    ocr_reader = models["ocr_reader"]

    tracker = VehicleTracker(camera_id=job.camera_id, job_id=job.id)
    voters: Dict[int, PlateVoter] = {}
    emitted_tracks: Set[int] = set()
    track_meta: Dict[int, Dict[str, Any]] = {}
    frames_processed = 0

    try:
        source_uri = job.source_uri
        # If source is an upload URI or file, verify existence if it's a local file path
        if not source_uri.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
            if not os.path.exists(source_uri):
                raise FileNotFoundError(f"Video file not found: {source_uri}")

        frame_source = FrameSource(source_uri, start_time=job.started_at)
        with frame_source:
            for frame, frame_index, utc_ts in frame_source:
                frames_processed += 1

                # 1. Vehicle detection + ByteTrack
                tracked_vehicles = tracker.track_frame(
                    frame=frame, frame_index=frame_index, detector=detector
                )

                # 2. Plate detection, OCR & voting per vehicle
                h, w = frame.shape[:2]
                for tv in tracked_vehicles:
                    tid = tv.track_id
                    if tid in emitted_tracks:
                        continue

                    # Crop vehicle bbox
                    bx1, by1, bx2, by2 = tv.bbox_xyxy
                    x1 = max(0, min(w - 1, int(round(bx1))))
                    y1 = max(0, min(h - 1, int(round(by1))))
                    x2 = max(0, min(w, int(round(bx2))))
                    y2 = max(0, min(h, int(round(by2))))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    vehicle_crop = frame[y1:y2, x1:x2]
                    norm_plate, conf, _crop = process_vehicle_crop_for_plate(
                        vehicle_crop,
                        plate_detector=plate_detector,
                        ocr_reader=ocr_reader,
                    )

                    if norm_plate:
                        if tid not in voters:
                            voters[tid] = PlateVoter(track_id=tid)
                            track_meta[tid] = {
                                "best_conf": -1.0,
                                "best_frame": None,
                                "best_ts": utc_ts,
                                "vehicle_class": tv.vehicle_class,
                            }

                        track_meta[tid]["vehicle_class"] = tv.vehicle_class
                        if conf > track_meta[tid]["best_conf"]:
                            track_meta[tid]["best_conf"] = conf
                            track_meta[tid]["best_frame"] = frame.copy()
                            track_meta[tid]["best_ts"] = utc_ts

                        voter = voters[tid]
                        vote_result = voter.add_read(norm_plate, conf)
                        if vote_result is not None:
                            # Finalized automatically at max_frames (15)
                            await emit_sighting(
                                track_id=tid,
                                vote_result=vote_result,
                                track_meta=track_meta[tid],
                                job=job,
                                camera=camera,
                                session=session,
                                emitted_tracks=emitted_tracks,
                            )

        # Video finished: finalize any tracks with at least min_frames (5)
        for tid, voter in voters.items():
            if tid not in emitted_tracks and voter.can_finalize():
                vote_res = voter.finalize()
                if vote_res is not None:
                    await emit_sighting(
                        track_id=tid,
                        vote_result=vote_res,
                        track_meta=track_meta.get(tid, {}),
                        job=job,
                        camera=camera,
                        session=session,
                        emitted_tracks=emitted_tracks,
                    )

        # Mark job as completed
        job.status = JobStatus.done
        job.frames_processed = frames_processed
        job.finished_at = datetime.now(timezone.utc)
        await session.commit()

        log_event(
            logging.INFO,
            "job_processing_completed",
            job_id=job.id,
            frames_processed=frames_processed,
            sightings_emitted=len(emitted_tracks),
        )

    except Exception as exc:
        job.status = JobStatus.failed
        job.error = str(exc)
        job.frames_processed = frames_processed
        job.finished_at = datetime.now(timezone.utc)
        await session.commit()

        log_event(
            logging.ERROR,
            "job_processing_failed",
            job_id=job.id,
            error=str(exc),
            frames_processed=frames_processed,
        )


class InferenceWorker:
    """Worker task polling queued jobs and running inference."""

    def __init__(
        self,
        worker_id: int = 1,
        poll_interval: Optional[float] = None,
        models: Optional[Dict[str, Any]] = None,
    ):
        self.worker_id = worker_id
        self.poll_interval = (
            poll_interval
            if poll_interval is not None
            else settings.worker_poll_interval
        )
        self.models = models
        self.running: bool = False

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run worker loop until stop_event is signaled."""
        self.running = True
        log_event(logging.INFO, "worker_loop_started", worker_id=self.worker_id)
        try:
            while not stop_event.is_set():
                claimed = False
                try:
                    async with AsyncSession() as session:
                        job = await claim_next_job(session)
                        if job:
                            claimed = True
                            log_event(
                                logging.INFO,
                                "job_claimed",
                                worker_id=self.worker_id,
                                job_id=job.id,
                                camera_id=job.camera_id,
                            )
                            await process_job(job.id, session, models=self.models)
                except Exception as exc:
                    log_event(
                        logging.ERROR,
                        "worker_loop_error",
                        worker_id=self.worker_id,
                        error=str(exc),
                    )

                if not claimed:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval)
                    except asyncio.TimeoutError:
                        pass
        finally:
            self.running = False

        log_event(logging.INFO, "worker_loop_stopped", worker_id=self.worker_id)


async def run_workers(
    concurrency: Optional[int] = None,
    poll_interval: Optional[float] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Run concurrent worker tasks with shared preloaded models and signal handling."""
    if concurrency is None:
        env_val = os.getenv("WORKER_CONCURRENCY") or os.getenv("RT_WORKER_CONCURRENCY")
        concurrency = int(env_val) if env_val else settings.worker_concurrency
    concurrency = max(1, concurrency)

    if stop_event is None:
        stop_event = asyncio.Event()

        def _handle_signal(signum: int, _frame: Any) -> None:
            log_event(logging.INFO, "shutdown_signal_received", signal=signum)
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, None))
            except (NotImplementedError, AttributeError):
                signal.signal(sig, _handle_signal)

    # Preload all model weights once at startup
    models = load_all_models()

    log_event(logging.INFO, "workers_starting", concurrency=concurrency)
    workers = [
        InferenceWorker(worker_id=i + 1, poll_interval=poll_interval, models=models)
        for i in range(concurrency)
    ]
    tasks = [asyncio.create_task(w.run(stop_event)) for w in workers]
    await asyncio.gather(*tasks)
    log_event(logging.INFO, "workers_shutdown_complete")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )
    try:
        asyncio.run(run_workers())
    except (KeyboardInterrupt, SystemExit):
        log_event(logging.INFO, "worker_process_terminated")
