"""Unit tests for inference worker, sighting emission, and API process isolation."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import seed_database
from app.db.session import AsyncSession
from app.inference.plate_ocr import VoteResult
from app.models.camera import Camera
from app.models.enums import JobStatus, VehicleClass
from app.models.processing_job import ProcessingJob
from app.models.sighting import Sighting
from app.models.vehicle import Vehicle
from app.services.matching_service import matching_service
from app.workers.inference_worker import (
    InferenceWorker,
    claim_next_job,
    emit_sighting,
    load_all_models,
    process_job,
)


@pytest.fixture(autouse=True, scope="module")
def setup_seed():
    seed_database()


@pytest.fixture
def test_camera_id():
    # Return camera ID 1 from seeded cameras
    return 1


@pytest.mark.asyncio
async def test_api_process_never_imports_torch():
    """Verify that importing app.main and API routes does not load torch into sys.modules.

    In production/Docker, the API container must remain lightweight and never load torch.
    """
    backend_dir = str(Path(__file__).resolve().parent.parent)
    code = """
import sys
assert 'torch' not in sys.modules, 'torch was already loaded before import'
import app.main
assert 'torch' not in sys.modules, f'torch was imported by app.main! Modules: {[m for m in sys.modules if "torch" in m]}'
print('SUCCESS_NO_TORCH')
"""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        cwd=backend_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, f"Subprocess failed: {stderr.decode()}"
    assert "SUCCESS_NO_TORCH" in stdout.decode()


@pytest.mark.asyncio
async def test_claim_next_job_for_update_skip_locked(test_camera_id):
    """Verify claim_next_job locks and updates queued job to running with started_at."""
    async with AsyncSession() as session:
        # Drain any pre-existing queued jobs from previous test fixtures
        while True:
            existing = await claim_next_job(session)
            if not existing:
                break

    async with AsyncSession() as session:
        job = ProcessingJob(
            camera_id=test_camera_id,
            source_uri="test_stream.mp4",
            status=JobStatus.queued,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    async with AsyncSession() as session:
        claimed = await claim_next_job(session)
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.status == JobStatus.running
        assert claimed.started_at is not None
        assert claimed.started_at.tzinfo is not None

        # Subsequent claim should return None if no other queued jobs exist
        next_claimed = await claim_next_job(session)
        assert next_claimed is None


@pytest.mark.asyncio
async def test_emit_sighting_exact_one_and_no_duplicates(tmp_path, test_camera_id):
    """Verify that emit_sighting writes exactly one sighting with all required fields

    and never emits duplicates for the same track_id.
    """
    snapshots_dir = tmp_path / "test_snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(settings, "snapshots_dir", str(snapshots_dir)):
        async with AsyncSession() as session:
            # Create a test job and camera
            camera = await session.get(Camera, test_camera_id)
            assert camera is not None

            job = ProcessingJob(
                camera_id=camera.id,
                source_uri="test_video.mp4",
                status=JobStatus.running,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            vote_result = VoteResult(
                plate_number="MH12DE1433",
                agreement_fraction=0.9,
                total_confidence=8.5,
                frames_voted=10,
                is_final=True,
            )

            dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            utc_now = datetime.now(timezone.utc)
            track_meta = {
                "best_conf": 0.95,
                "best_frame": dummy_frame,
                "best_ts": utc_now,
                "vehicle_class": VehicleClass.passenger_car,
            }

            emitted_tracks = set()

            # Mock matching_service.ingest_sighting to verify it is called
            with patch.object(
                matching_service, "ingest_sighting", new_callable=AsyncMock
            ) as mock_ingest:
                sighting = await emit_sighting(
                    track_id=42,
                    vote_result=vote_result,
                    track_meta=track_meta,
                    job=job,
                    camera=camera,
                    session=session,
                    emitted_tracks=emitted_tracks,
                )

                assert sighting is not None
                assert sighting.plate_number == "MH12DE1433"
                assert sighting.camera_id == camera.id
                assert sighting.track_id == 42
                assert sighting.vehicle_class == VehicleClass.passenger_car
                assert sighting.frames_voted == 10
                assert sighting.timestamp.tzinfo is not None
                assert sighting.snapshot_path is not None
                assert os.path.exists(sighting.snapshot_path)
                assert sighting.location is not None

                # Verify Vehicle record was created/updated
                v_res = await session.execute(
                    select(Vehicle).where(Vehicle.plate_number == "MH12DE1433")
                )
                veh = v_res.scalar_one_or_none()
                assert veh is not None
                assert veh.sighting_count >= 1

                # Verify matching_service.ingest_sighting was called
                mock_ingest.assert_awaited_once_with(sighting, db=session)

                # Attempt second emission for the same track_id -> MUST return None (no duplicate)
                dup_sighting = await emit_sighting(
                    track_id=42,
                    vote_result=vote_result,
                    track_meta=track_meta,
                    job=job,
                    camera=camera,
                    session=session,
                    emitted_tracks=emitted_tracks,
                )
                assert dup_sighting is None

                # Verify only 1 sighting exists in DB for this track
                s_res = await session.execute(
                    select(Sighting).where(
                        Sighting.job_id == job.id, Sighting.track_id == 42
                    )
                )
                sightings_list = s_res.scalars().all()
                assert len(sightings_list) == 1


@pytest.mark.asyncio
async def test_process_job_failure_updates_status_and_error(test_camera_id):
    """Verify that processing failure sets status=failed, records error text and finished_at."""
    async with AsyncSession() as session:
        job = ProcessingJob(
            camera_id=test_camera_id,
            source_uri="non_existent_file_path_12345.mp4",
            status=JobStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    async with AsyncSession() as session:
        await process_job(job_id=job_id, session=session)

    async with AsyncSession() as session:
        refreshed = await session.get(ProcessingJob, job_id)
        assert refreshed.status == JobStatus.failed
        assert refreshed.error is not None
        assert "not found" in refreshed.error.lower()
        assert refreshed.finished_at is not None
        assert refreshed.finished_at.tzinfo is not None


@pytest.mark.asyncio
async def test_process_job_synthetic_video_pipeline(tmp_path, test_camera_id):
    """Verify end-to-end process_job pipeline with a generated video file and mocked inference."""
    # Create a 15-frame synthetic MP4 video
    video_path = tmp_path / "synthetic_car.mp4"
    h, w = 480, 640
    fps = 25.0
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(video_path), fourcc, fps, (w, h))
    for i in range(15):
        frame = np.ones((h, w, 3), dtype=np.uint8) * 120
        # Draw simulated vehicle rectangle
        cv2.rectangle(frame, (100, 100), (300, 300), (40, 40, 200), -1)
        out.write(frame)
    out.release()

    snapshots_dir = tmp_path / "test_snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(settings, "snapshots_dir", str(snapshots_dir)):
        async with AsyncSession() as session:
            job = ProcessingJob(
                camera_id=test_camera_id,
                source_uri=str(video_path),
                status=JobStatus.running,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        # Mock tracker and OCR so it reliably returns a detected tracked vehicle and plate
        from app.inference.tracker import TrackedVehicle

        mock_tv = TrackedVehicle(
            track_id=99,
            bbox_xyxy=(100.0, 100.0, 300.0, 300.0),
            conf=0.92,
            vehicle_class=VehicleClass.passenger_car,
            frame_index=0,
        )

        with patch("app.workers.inference_worker.VehicleTracker.track_frame") as mock_track:
            mock_track.return_value = [mock_tv]
            with patch("app.workers.inference_worker.process_vehicle_crop_for_plate") as mock_ocr:
                mock_ocr.return_value = ("KA01AB9999", 0.94, np.zeros((30, 100, 3), dtype=np.uint8))

                async with AsyncSession() as session:
                    await process_job(job_id=job_id, session=session)

        async with AsyncSession() as session:
            refreshed = await session.get(ProcessingJob, job_id)
            assert refreshed.status == JobStatus.done
            assert refreshed.frames_processed == 15
            assert refreshed.finished_at is not None

            # Verify sighting was written
            s_res = await session.execute(
                select(Sighting).where(Sighting.job_id == job_id, Sighting.track_id == 99)
            )
            sightings = s_res.scalars().all()
            assert len(sightings) == 1
            assert sightings[0].plate_number == "KA01AB9999"
            assert sightings[0].frames_voted >= 5
            assert sightings[0].snapshot_path is not None
            assert os.path.exists(sightings[0].snapshot_path)


@pytest.mark.asyncio
async def test_worker_graceful_shutdown():
    """Verify that InferenceWorker stops cleanly when stop_event is signaled."""
    worker = InferenceWorker(worker_id=1, poll_interval=0.05)
    stop_event = asyncio.Event()

    task = asyncio.create_task(worker.run(stop_event))
    await asyncio.sleep(0.1)
    assert worker.running is True

    # Signal stop
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert worker.running is False


def test_load_all_models_preloads_weights():
    """Verify load_all_models returns references to singletons."""
    models = load_all_models()
    assert "detector" in models
    assert "plate_detector" in models
    assert "ocr_reader" in models
