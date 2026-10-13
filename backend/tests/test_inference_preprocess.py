from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from app.core.config import settings
from app.inference.ingest import FrameSource
from app.inference.preprocess import (
    blur_score,
    enhance_plate,
    is_blurry,
    letterbox,
    unletterbox_box,
    unletterbox_boxes,
)


def test_letterbox_output_is_exactly_640x640():
    # Test multiple aspect ratios: landscape, portrait, square, extreme aspect ratio
    test_shapes = [
        (1080, 1920, 3),  # 16:9 landscape
        (1920, 1080, 3),  # 9:16 portrait
        (800, 800, 3),    # 1:1 square
        (300, 1200, 3),   # 4:1 wide
        (1200, 300, 3),   # 1:4 tall
    ]

    for h, w, c in test_shapes:
        img = np.random.randint(0, 256, (h, w, c), dtype=np.uint8)
        lb, scale, (pad_left, pad_top) = letterbox(img, target_size=640)

        assert lb.shape == (640, 640, 3), f"Expected (640, 640, 3), got {lb.shape} for ({h}, {w})"
        assert pad_left >= 0
        assert pad_top >= 0

        # Scale check
        expected_scale = min(640 / h, 640 / w)
        assert abs(scale - expected_scale) < 1e-6


def test_mapping_boxes_back_is_accurate_within_one_pixel():
    orig_h, orig_w = 1080, 1920
    img = np.zeros((orig_h, orig_w, 3), dtype=np.uint8)
    lb, scale, (pad_left, pad_top) = letterbox(img, target_size=640)

    # Test arbitrary vehicle/plate boxes inside original image
    test_boxes = [
        (100.0, 150.0, 500.0, 450.0),
        (350.0, 600.0, 800.0, 950.0),
        (0.0, 0.0, float(orig_w), float(orig_h)),
        (1200.0, 200.0, 1600.0, 700.0),
    ]

    for x1, y1, x2, y2 in test_boxes:
        # Project original box into letterbox coordinates
        x1_lb = x1 * scale + pad_left
        y1_lb = y1 * scale + pad_top
        x2_lb = x2 * scale + pad_left
        y2_lb = y2 * scale + pad_top

        # Restore box using unletterbox_box
        rx1, ry1, rx2, ry2 = unletterbox_box(
            (x1_lb, y1_lb, x2_lb, y2_lb),
            scale,
            (pad_left, pad_top),
            orig_shape=(orig_h, orig_w),
        )

        assert abs(rx1 - x1) <= 1.0, f"x1 error too large: {abs(rx1 - x1)}"
        assert abs(ry1 - y1) <= 1.0, f"y1 error too large: {abs(ry1 - y1)}"
        assert abs(rx2 - x2) <= 1.0, f"x2 error too large: {abs(rx2 - x2)}"
        assert abs(ry2 - y2) <= 1.0, f"y2 error too large: {abs(ry2 - y2)}"

    # Also test vectorized unletterbox_boxes
    boxes_array = np.array(
        [[x1 * scale + pad_left, y1 * scale + pad_top, x2 * scale + pad_left, y2 * scale + pad_top]
         for x1, y1, x2, y2 in test_boxes],
        dtype=np.float32,
    )
    restored_array = unletterbox_boxes(boxes_array, scale, (pad_left, pad_top), orig_shape=(orig_h, orig_w))
    for i, (x1, y1, x2, y2) in enumerate(test_boxes):
        assert abs(restored_array[i, 0] - x1) <= 1.0
        assert abs(restored_array[i, 1] - y1) <= 1.0
        assert abs(restored_array[i, 2] - x2) <= 1.0
        assert abs(restored_array[i, 3] - y2) <= 1.0


def test_blur_score_sharp_vs_gaussian_blurred():
    # Synthetic high-contrast checkerboard image (sharp)
    block_size = 16
    grid = np.indices((16, 16)).sum(axis=0) % 2
    sharp = np.kron(grid, np.ones((block_size, block_size), dtype=np.uint8)) * 255
    sharp = cv2.cvtColor(sharp.astype(np.uint8), cv2.COLOR_GRAY2BGR)

    # Heavily blurred image (Gaussian blur)
    blurred = cv2.GaussianBlur(sharp, (31, 31), 10)

    score_sharp = blur_score(sharp)
    score_blurred = blur_score(blurred)

    # Sharp image has high variance of Laplacian; blurred has very low variance
    assert score_sharp > 500.0, f"Expected high sharp score, got {score_sharp}"
    assert score_blurred < 50.0, f"Expected low blur score, got {score_blurred}"

    # Verify is_blurry with paper threshold tau = 100
    assert not is_blurry(sharp, tau=100)
    assert is_blurry(blurred, tau=100)

    # Verify default tau uses settings.blur_tau (which is 100)
    assert settings.blur_tau == 100
    assert not is_blurry(sharp)
    assert is_blurry(blurred)


def test_enhance_plate_pipeline():
    # Create synthetic number plate image: gray background with dark text
    plate = np.full((60, 200, 3), 200, dtype=np.uint8)
    cv2.putText(
        plate,
        "MH12AB1234",
        (10, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )

    enhanced_gray, binary = enhance_plate(plate)

    assert enhanced_gray.shape == (60, 200)
    assert binary.shape == (60, 200)

    # Binary image should only contain 0 and 255
    unique_vals = set(np.unique(binary).tolist())
    assert unique_vals.issubset({0, 255})

    # Assert config constants match paper specs
    assert settings.clahe_clip_limit == 2.0
    assert settings.clahe_tile_grid == (8, 8)
    assert settings.bilateral_d == 9
    assert settings.bilateral_sigma_color == 75.0
    assert settings.bilateral_sigma_space == 75.0


def test_frame_source_video_file(tmp_path: Path):
    video_path = tmp_path / "test_ingest.mp4"
    num_frames = 10
    fps = 10.0
    width, height = 120, 100

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.full((height, width, 3), i * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    t0 = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Step = 1 (all frames)
    source = FrameSource(video_path, start_time=t0, step=1)
    frames_read = []
    indices_read = []
    timestamps_read = []

    for frame, idx, ts in source:
        frames_read.append(frame)
        indices_read.append(idx)
        timestamps_read.append(ts)

    assert len(frames_read) == num_frames
    assert indices_read == list(range(num_frames))
    for i, ts in enumerate(timestamps_read):
        expected_ts = t0 + timedelta(seconds=i / fps)
        assert abs((ts - expected_ts).total_seconds()) < 1e-4

    # 2. Step = 2 (every 2nd frame: 0, 2, 4, 6, 8)
    source_step2 = FrameSource(video_path, start_time=t0, step=2)
    step2_indices = []
    step2_timestamps = []
    for frame, idx, ts in source_step2:
        step2_indices.append(idx)
        step2_timestamps.append(ts)

    assert step2_indices == [0, 2, 4, 6, 8]
    for idx, ts in zip(step2_indices, step2_timestamps):
        expected_ts = t0 + timedelta(seconds=idx / fps)
        assert abs((ts - expected_ts).total_seconds()) < 1e-4


def test_frame_source_rtsp_mode_and_reconnect():
    mock_cap1 = MagicMock()
    mock_cap1.isOpened.return_value = True
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    # Stream 1 returns 2 frames then disconnects
    mock_cap1.read.side_effect = [(True, dummy_frame), (True, dummy_frame), (False, None)]
    mock_cap1.get.return_value = 25.0

    mock_cap2 = MagicMock()
    mock_cap2.isOpened.return_value = True
    # Reconnected stream returns 1 frame then finishes
    mock_cap2.read.side_effect = [(True, dummy_frame), (False, None)]
    mock_cap2.get.return_value = 25.0

    mock_cap3 = MagicMock()
    mock_cap3.isOpened.return_value = False

    with patch("cv2.VideoCapture", side_effect=[mock_cap1, mock_cap2, mock_cap3]):
        source = FrameSource(
            "rtsp://192.168.1.100:554/live",
            max_reconnect_attempts=1,
            reconnect_delay=0.0,
        )
        assert source.is_rtsp is True

        frames = []
        for frame, idx, ts in source:
            frames.append((idx, ts))

        # First connection yielded 2 frames, reconnected yielded 1 frame
        assert len(frames) == 3
        assert frames[0][0] == 0
        assert frames[1][0] == 1
        assert frames[2][0] == 2

        # Timestamps for RTSP are wall-clock UTC
        now_utc = datetime.now(timezone.utc)
        assert (now_utc - frames[0][1]).total_seconds() < 5.0
