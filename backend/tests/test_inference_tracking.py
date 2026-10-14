from pathlib import Path

import pytest
import torch
from ultralytics.engine.results import Boxes

from app.core.config import settings
from app.inference.benchmark import generate_benchmark_clip, run_benchmark
from app.inference.detector import (
    COCO_TO_VEHICLE_CLASS,
    VEHICLE_CLASS_IDS,
    YOLODetector,
    get_detector,
)
from app.inference.tracker import (
    VehicleTracker,
    get_tracker,
    reset_trackers,
)
from app.models.enums import VehicleClass


def test_detector_singleton():
    d1 = get_detector()
    d2 = get_detector()
    d3 = YOLODetector()

    assert d1 is d2
    assert d2 is d3
    assert d1.model is d2.model


def test_vehicle_classes_mapping():
    assert set(VEHICLE_CLASS_IDS) == {2, 3, 5, 7}
    assert COCO_TO_VEHICLE_CLASS[2] == VehicleClass.passenger_car
    assert COCO_TO_VEHICLE_CLASS[3] == VehicleClass.two_wheeler
    assert COCO_TO_VEHICLE_CLASS[5] == VehicleClass.public_bus
    assert COCO_TO_VEHICLE_CLASS[7] == VehicleClass.commercial_truck


def test_thresholds_match_paper():
    # Paper requirement: conf < 0.45 dropped, NMS IoU 0.50
    assert settings.vehicle_conf == 0.45
    assert settings.nms_iou == 0.50


def test_bytetrack_second_association_pass_and_stable_id():
    # ByteTrack must keep low-confidence boxes (e.g. 0.35 < 0.45) in the second association pass
    # to maintain track continuity through occlusions, while filtering conf < 0.45 from final output.
    tracker = VehicleTracker(camera_id="test_cam")

    # Frame 1: Vehicle detected clearly (conf = 0.85 >= 0.45)
    b1 = Boxes(
        torch.tensor([[100.0, 100.0, 200.0, 200.0, 0.85, 2.0]]),
        orig_shape=(640, 640),
    )
    t1 = tracker.update(b1.cpu().numpy(), frame_index=0)
    assert len(t1) == 1
    vehicle_id = t1[0].track_id
    assert t1[0].conf == pytest.approx(0.85, abs=1e-2)
    assert t1[0].vehicle_class == VehicleClass.passenger_car

    # Frame 2: Vehicle partially occluded by a bus (conf = 0.35, below 0.45 output threshold)
    # The low-score box is used in ByteTrack's 2nd association pass, but discarded from output
    b2 = Boxes(
        torch.tensor([[103.0, 102.0, 203.0, 202.0, 0.35, 2.0]]),
        orig_shape=(640, 640),
    )
    t2 = tracker.update(b2.cpu().numpy(), frame_index=1)
    # Filtered from output because conf (0.35) < 0.45
    assert len(t2) == 0

    # Frame 3: Vehicle emerges from occlusion (conf = 0.80 >= 0.45)
    b3 = Boxes(
        torch.tensor([[106.0, 104.0, 206.0, 204.0, 0.80, 2.0]]),
        orig_shape=(640, 640),
    )
    t3 = tracker.update(b3.cpu().numpy(), frame_index=2)
    assert len(t3) == 1
    # Track ID must be preserved from Frame 1!
    assert t3[0].track_id == vehicle_id, (
        f"Track ID changed after occlusion: expected {vehicle_id}, got {t3[0].track_id}"
    )


def test_tracker_isolation_across_cameras():
    reset_trackers()

    # Two separate cameras
    cam1_tracker = get_tracker("CAM_Kathipara")
    cam2_tracker = get_tracker("CAM_Airport")

    assert cam1_tracker is not cam2_tracker
    assert cam1_tracker.tracker is not cam2_tracker.tracker

    # Cam 1 receives detection
    b1 = Boxes(
        torch.tensor([[50.0, 50.0, 150.0, 150.0, 0.9, 2.0]]),
        orig_shape=(640, 640),
    )
    t1 = cam1_tracker.update(b1.cpu().numpy(), frame_index=0)
    assert len(t1) == 1
    cam1_id = t1[0].track_id

    # Cam 2 receives detection at different location
    b2 = Boxes(
        torch.tensor([[300.0, 300.0, 400.0, 400.0, 0.9, 3.0]]),
        orig_shape=(640, 640),
    )
    t2 = cam2_tracker.update(b2.cpu().numpy(), frame_index=0)
    assert len(t2) == 1
    cam2_id = t2[0].track_id

    # Both start their own sequence from ID 1 without interference
    assert cam1_id == 1
    assert cam2_id == 1
    assert t2[0].vehicle_class == VehicleClass.two_wheeler


def test_stable_track_ids_on_synthetic_clip(tmp_path: Path):
    # Short fixture clip with 10 frames
    clip_path = tmp_path / "fixture_clip.mp4"
    num_frames = 10
    generate_benchmark_clip(clip_path, num_frames=num_frames, width=640, height=360)

    tracker = VehicleTracker(camera_id="fixture_cam")

    frame_indices = []
    track_ids_seen = set()
    per_frame_ids = []

    # Using synthetic detections that smoothly translate across frames
    for i in range(num_frames):
        x1 = 100.0 + i * 8.0
        y1 = 120.0 + i * 2.0
        x2 = x1 + 100.0
        y2 = y1 + 50.0

        boxes = Boxes(
            torch.tensor([[x1, y1, x2, y2, 0.88, 2.0]]),
            orig_shape=(360, 640),
        )

        tracked = tracker.update(boxes.cpu().numpy(), frame_index=i)
        assert len(tracked) == 1
        per_frame_ids.append(tracked[0].track_id)
        track_ids_seen.add(tracked[0].track_id)
        frame_indices.append(i)

    # Exactly 1 stable track ID throughout all 10 frames
    assert len(track_ids_seen) == 1, f"Track ID switched unexpectedly: seen {track_ids_seen}"
    assert all(tid == per_frame_ids[0] for tid in per_frame_ids)


def test_benchmark_execution(tmp_path: Path):
    # Run a quick 5-frame benchmark to ensure script executes without error
    clip_path = tmp_path / "quick_bench.mp4"
    generate_benchmark_clip(clip_path, num_frames=5, width=640, height=360)

    result = run_benchmark(video_path=str(clip_path), num_frames=5)
    assert result["frames"] == 5
    assert result["fps"] > 0.0
    assert result["elapsed_sec"] > 0.0
