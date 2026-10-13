import argparse
from pathlib import Path
import tempfile
import time
from typing import Optional

import cv2
import numpy as np

from app.inference.detector import get_detector
from app.inference.ingest import FrameSource
from app.inference.tracker import VehicleTracker


def generate_benchmark_clip(
    output_path: Path,
    num_frames: int = 60,
    width: int = 1280,
    height: int = 720,
    fps: float = 30.0,
) -> Path:
    """Generate a synthetic video clip with moving vehicles for benchmarking."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    for i in range(num_frames):
        # Road background
        frame = np.full((height, width, 3), 60, dtype=np.uint8)
        cv2.line(frame, (0, height // 2), (width, height // 2), (255, 255, 255), 2)

        # Vehicle 1 moving right
        x1 = int(50 + i * 15) % (width - 150)
        y1 = 200
        cv2.rectangle(frame, (x1, y1), (x1 + 140, y1 + 70), (0, 0, 200), -1)

        # Vehicle 2 moving left
        x2 = int(width - 200 - i * 12) % (width - 150)
        y2 = 450
        cv2.rectangle(frame, (x2, y2), (x2 + 160, y2 + 80), (200, 100, 0), -1)

        writer.write(frame)

    writer.release()
    return output_path


def run_benchmark(
    video_path: Optional[str] = None,
    num_frames: int = 60,
    step: int = 1,
) -> dict:
    """Benchmark end-to-end detection and tracking throughput."""
    temp_file: Optional[Path] = None
    if video_path is None or not Path(video_path).exists():
        temp_file = Path(tempfile.gettempdir()) / "benchmark_sample.mp4"
        generate_benchmark_clip(temp_file, num_frames=num_frames)
        target_video = str(temp_file)
        print(f"Generated synthetic benchmark clip: {target_video} ({num_frames} frames)")
    else:
        target_video = video_path

    detector = get_detector()
    tracker = VehicleTracker(camera_id="bench_cam_01")

    frame_source = FrameSource(target_video, step=step)

    print("Warming up model...")
    warmup_frame = np.zeros((640, 640, 3), dtype=np.uint8)
    for _ in range(3):
        detector.detect_raw(warmup_frame, conf=0.1)

    print("Running benchmark...")
    total_frames = 0
    total_tracked = 0
    start_time = time.perf_counter()

    for frame, idx, ts in frame_source:
        tracked = tracker.track_frame(frame, frame_index=idx, detector=detector)
        total_tracked += len(tracked)
        total_frames += 1

    elapsed = time.perf_counter() - start_time
    fps = total_frames / elapsed if elapsed > 0 else 0.0
    ms_per_frame = (elapsed / total_frames * 1000.0) if total_frames > 0 else 0.0

    print("=" * 50)
    print(" ROADTRACE AI - INFERENCE & TRACKING BENCHMARK")
    print("=" * 50)
    print(f"Total Frames Processed : {total_frames}")
    print(f"Total Vehicles Tracked : {total_tracked}")
    print(f"Total Elapsed Time     : {elapsed:.3f} s")
    print(f"Average Throughput     : {fps:.2f} FPS")
    print(f"Average Latency        : {ms_per_frame:.2f} ms/frame")
    print("=" * 50)

    if temp_file and temp_file.exists():
        try:
            temp_file.unlink()
        except Exception:
            pass

    return {
        "frames": total_frames,
        "tracked": total_tracked,
        "elapsed_sec": elapsed,
        "fps": fps,
        "ms_per_frame": ms_per_frame,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RoadTrace AI Inference Benchmark")
    parser.add_argument("--video", type=str, default=None, help="Path to video file")
    parser.add_argument("--frames", type=int, default=60, help="Number of synthetic frames")
    parser.add_argument("--step", type=int, default=1, help="Process every Nth frame")
    args = parser.parse_args()

    run_benchmark(video_path=args.video, num_frames=args.frames, step=args.step)
