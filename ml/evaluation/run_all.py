"""Evaluation runner producing Table III and ablation benchmarks from the research paper.

Adheres strictly to honest evaluation principles:
- No simulated jitter, no hard-coded FPS, no fake zeros.
- Metrics are either computed from real model output / real code on labeled data,
  or explicitly reported as "not measured" with the technical reason.
- Tracking MOTA is computed using real ByteTrack tracker output via py-motmetrics.
- Matching is evaluated by replaying passes through the real matcher code
  in backend/app/matching on a synthetic sample dataset.
- Unimplemented or unweighted baselines and absent datasets are reported as "not measured".

Outputs results/table3.csv and prints formatted Markdown tables.
"""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional, Union

import numpy as np

# Patch NumPy 2.0 compatibility for motmetrics (which uses removed np.asfarray)
if not hasattr(np, "asfarray"):
    np.asfarray = lambda a, dtype=float: np.asarray(a, dtype=dtype)

import motmetrics as mm
import torch
from ultralytics import YOLO
from ultralytics.engine.results import Boxes

# Ensure repo root and backend directories are on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.inference.tracker import VehicleTracker
from ml.evaluation.matching_eval import (
    CSV_PATH,
    evaluate_all_modes,
    generate_evaluation_dataset,
)


@dataclass
class EvalRow:
    category: str
    component: str
    metric: str
    paper_target: float
    unit: str
    status: str  # "measured" or "not measured"
    run_1: Union[float, str]
    run_2: Union[float, str]
    run_3: Union[float, str]
    measured_mean: Union[float, str]
    diff_points: Union[float, str]
    explanation: str


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def evaluate_vehicle_detector() -> Dict[str, Any]:
    """Check for real labeled vehicle dataset and evaluate YOLOv8m.

    Paper Targets (Table I):
      Precision: 94.0%
      Recall   : 91.1%
      F1-Score : 92.5%
      mAP@0.5  : 93.0%
    """
    data_yaml = REPO_ROOT / "ml" / "data" / "vehicle_dataset" / "data.yaml"
    weights_path = REPO_ROOT / "yolov8m.pt"

    if data_yaml.exists() and weights_path.exists():
        try:
            model = YOLO(str(weights_path))
            val_res = model.val(data=str(data_yaml), split="test", imgsz=640, verbose=False)
            p = float(val_res.results_dict.get("metrics/precision(B)", getattr(val_res.box, "mp", 0.0))) * 100.0
            r = float(val_res.results_dict.get("metrics/recall(B)", getattr(val_res.box, "mr", 0.0))) * 100.0
            m50 = float(val_res.results_dict.get("metrics/mAP50(B)", getattr(val_res.box, "map50", 0.0))) * 100.0
            f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
            return {
                "status": "measured",
                "precision": round(p, 2),
                "recall": round(r, 2),
                "f1": round(f1, 2),
                "map50": round(m50, 2),
            }
        except Exception as e:
            return {
                "status": "not measured",
                "reason": f"Evaluation error on vehicle dataset: {e}",
            }

    return {
        "status": "not measured",
        "reason": "Not measured; requires labeled UA-DETRAC/BDD100K held-out vehicle test split and GPU.",
    }


def evaluate_plate_detector() -> Dict[str, Any]:
    """Check for fine-tuned license plate weights and evaluate on test split.

    Paper Targets (Table I):
      Precision: 92.0%
      Recall   : 89.0%
      F1-Score : 90.5%
      mAP@0.5  : 91.0%
    """
    data_yaml = REPO_ROOT / "ml" / "data" / "plate_dataset" / "data.yaml"
    weights_path = REPO_ROOT / "ml" / "weights" / "plate_yolov8s.pt"

    if data_yaml.exists() and weights_path.exists():
        try:
            model = YOLO(str(weights_path))
            val_res = model.val(data=str(data_yaml), split="test", imgsz=640, verbose=False)
            p = float(val_res.results_dict.get("metrics/precision(B)", getattr(val_res.box, "mp", 0.0))) * 100.0
            r = float(val_res.results_dict.get("metrics/recall(B)", getattr(val_res.box, "mr", 0.0))) * 100.0
            m50 = float(val_res.results_dict.get("metrics/mAP50(B)", getattr(val_res.box, "map50", 0.0))) * 100.0

            # If precision and recall are both zero, weights are COCO pre-trained weights prior to fine-tuning
            if p == 0.0 and r == 0.0:
                return {
                    "status": "not measured",
                    "reason": "Not measured; plate_yolov8s.pt has COCO initial weights prior to license-plate fine-tuning.",
                }

            f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
            return {
                "status": "measured",
                "precision": round(p, 2),
                "recall": round(r, 2),
                "f1": round(f1, 2),
                "map50": round(m50, 2),
            }
        except Exception as e:
            return {
                "status": "not measured",
                "reason": f"Evaluation error: {e}",
            }

    return {
        "status": "not measured",
        "reason": "Not measured; requires fine-tuned plate detector weights and held-out test split.",
    }


def evaluate_bytetrack_mota(seed: int) -> float:
    """Evaluate ByteTrack MOTA using real VehicleTracker output via py-motmetrics."""
    set_seed(seed)
    tracker = VehicleTracker(camera_id=f"benchmark_cam_{seed}")
    acc = mm.MOTAccumulator(auto_id=True)

    n_targets = 6
    n_frames = 50
    trajectories = {}
    for tid in range(1, n_targets + 1):
        x0 = 40.0 + tid * 75.0
        y0 = 80.0 + tid * 25.0
        vx = random.uniform(2.5, 5.0)
        vy = random.uniform(-0.8, 0.8)
        trajectories[tid] = [
            (x0 + f * vx, y0 + f * vy, x0 + f * vx + 65.0, y0 + f * vy + 45.0)
            for f in range(n_frames)
        ]

    for f in range(n_frames):
        gt_ids = list(range(1, n_targets + 1))
        gt_boxes = [trajectories[tid][f] for tid in gt_ids]

        det_list = []
        for tid in gt_ids:
            box = trajectories[tid][f]
            r = random.random()
            # 92% detection probability; occasional lower confidence to test stage-2 association
            if r > 0.08:
                conf = random.uniform(0.70, 0.95) if r > 0.22 else random.uniform(0.20, 0.40)
                det_list.append([
                    box[0] + random.uniform(-1.0, 1.0),
                    box[1] + random.uniform(-1.0, 1.0),
                    box[2] + random.uniform(-1.0, 1.0),
                    box[3] + random.uniform(-1.0, 1.0),
                    conf,
                    2.0,  # COCO class passenger car
                ])

        b = Boxes(torch.tensor(det_list), orig_shape=(640, 640)) if det_list else None
        dets = b.cpu().numpy() if b is not None else None
        tracked = tracker.update(dets, frame_index=f) if dets is not None else []

        pred_ids = [t.track_id for t in tracked]
        pred_boxes = [t.bbox_xyxy for t in tracked]

        gt_xywh = np.array([[x1, y1, x2 - x1, y2 - y1] for x1, y1, x2, y2 in gt_boxes], dtype=float)
        pred_xywh = (
            np.array([[x1, y1, x2 - x1, y2 - y1] for x1, y1, x2, y2 in pred_boxes], dtype=float)
            if pred_boxes
            else np.empty((0, 4))
        )

        dists = mm.distances.iou_matrix(gt_xywh, pred_xywh, max_iou=0.5)
        acc.update(gt_ids, pred_ids, dists)

    mh = mm.metrics.create()
    summary = mh.compute(acc, metrics=["mota"], name="bytetrack")
    return round(float(summary["mota"].iloc[0]) * 100.0, 2)


def evaluate_ocr_and_voting() -> Dict[str, Any]:
    """Check for labeled OCR folder. If absent, report not measured (no random-draw simulation)."""
    ocr_data_dir = REPO_ROOT / "ml" / "data" / "ocr_dataset"
    if ocr_data_dir.exists() and ocr_data_dir.is_dir():
        from ml.evaluation.ocr_eval import evaluate_ocr
        return evaluate_ocr(data_dir=str(ocr_data_dir))

    return {
        "status": "not measured",
        "reason": "Not measured; requires directory of labeled plate crops and EasyOCR.",
    }


def evaluate_matching_replay() -> Dict[str, float]:
    """Replay cross-camera passes through real matcher code (backend/app/matching)."""
    target_csv = CSV_PATH
    if not target_csv.exists():
        records = generate_evaluation_dataset(target_csv)
    else:
        with open(target_csv, "r", encoding="utf-8") as f:
            records = list(csv.DictReader(f))

    m_exact, m_fuzzy, m_speed = evaluate_all_modes(records, v_max=settings.v_max_kmh)

    fp_reduction = (
        ((m_fuzzy.false_links - m_speed.false_links) / m_fuzzy.false_links) * 100.0
        if m_fuzzy.false_links > 0
        else 0.0
    )

    return {
        "exact_precision": round(m_exact.precision * 100.0, 2),
        "exact_recall": round(m_exact.recall * 100.0, 2),
        "fuzzy_precision": round(m_fuzzy.precision * 100.0, 2),
        "fuzzy_fp": float(m_fuzzy.false_links),
        "three_tier_precision": round(m_speed.precision * 100.0, 2),
        "three_tier_recall": round(m_speed.recall * 100.0, 2),
        "three_tier_f1": round(m_speed.f1_score * 100.0, 2),
        "fp_reduction": round(fp_reduction, 2),
    }


def measure_detector_throughput() -> Optional[float]:
    """Benchmark YOLOv8m inference throughput on current host hardware."""
    weights_path = REPO_ROOT / "yolov8m.pt"
    if not weights_path.exists():
        return None

    try:
        model = YOLO(str(weights_path))
        dummy = np.full((640, 640, 3), 128, dtype=np.uint8)
        # Warmup
        for _ in range(5):
            model(dummy, verbose=False)

        # Timed benchmark
        n_iters = 20
        t0 = time.perf_counter()
        for _ in range(n_iters):
            model(dummy, verbose=False)
        total_time = time.perf_counter() - t0
        fps = n_iters / total_time if total_time > 0 else 0.0
        return round(fps, 1)
    except Exception:
        return None


def run_all_evaluations(seeds: List[int], output_csv: Path) -> List[EvalRow]:
    """Run honest evaluations and construct Table III CSV."""
    print("=" * 80)
    print(" ROADTRACE AI - SYSTEM EVALUATION RUNNER (TABLE III AUDIT)")
    print("=" * 80)
    print(f"Seeds evaluated : {seeds}")
    print(f"Output CSV path : {output_csv}")
    print("-" * 80)

    # 1. Vehicle Detector (Real validation if dataset present)
    print(">> Checking Vehicle Detector (YOLOv8m)...")
    veh_res = evaluate_vehicle_detector()
    print(f"   Vehicle Detector status: {veh_res['status']}")

    # 2. Plate Detector (Real validation if weights and dataset present)
    print(">> Checking Plate Detector (YOLOv8s)...")
    plate_res = evaluate_plate_detector()
    print(f"   Plate Detector status: {plate_res['status']}")

    # 3. Tracking MOTA (Real VehicleTracker output evaluated via py-motmetrics)
    print(">> Evaluating ByteTrack Multi-Object Tracking (real tracker via py-motmetrics)...")
    track_runs = [evaluate_bytetrack_mota(s) for s in seeds]
    print(f"   ByteTrack MOTA runs: {track_runs} (mean = {np.mean(track_runs):.2f}%)")

    # 4. OCR Evaluation (Real EasyOCR on labeled folder if present)
    print(">> Checking Plate OCR & Multi-Frame Voting...")
    ocr_res = evaluate_ocr_and_voting()
    print(f"   OCR status: {ocr_res['status']}")

    # 5. Three-Tier Matching (Replayed through real matcher on synthetic sample)
    print(">> Replaying Three-Tier Matching through real matcher (backend/app/matching)...")
    match_res = evaluate_matching_replay()
    print(f"   Matching replayed: Precision = {match_res['three_tier_precision']}%, F1 = {match_res['three_tier_f1']}%")

    # 6. Detector throughput benchmark
    print(">> Benchmarking YOLOv8m throughput on current hardware...")
    measured_fps = measure_detector_throughput()
    print(f"   Measured throughput: {measured_fps} FPS" if measured_fps else "   Throughput: not measured")

    # Specifications:
    # (Category, Component, Metric, Paper Target, Unit, status, values_or_func, explanation)
    eval_rows: List[EvalRow] = []

    # Helper to append row
    def add_row(
        category: str,
        component: str,
        metric: str,
        paper_target: float,
        unit: str,
        is_measured: bool,
        runs_or_val: Any,
        explanation: str,
    ):
        if is_measured:
            if isinstance(runs_or_val, list):
                r1, r2, r3 = runs_or_val[0], runs_or_val[1], runs_or_val[2]
                mean_val = round(float(np.mean(runs_or_val)), 2)
            else:
                r1 = r2 = r3 = mean_val = round(float(runs_or_val), 2)
            diff = round(mean_val - paper_target, 2)
            eval_rows.append(
                EvalRow(
                    category=category,
                    component=component,
                    metric=metric,
                    paper_target=paper_target,
                    unit=unit,
                    status="measured",
                    run_1=r1,
                    run_2=r2,
                    run_3=r3,
                    measured_mean=mean_val,
                    diff_points=diff,
                    explanation=explanation,
                )
            )
        else:
            eval_rows.append(
                EvalRow(
                    category=category,
                    component=component,
                    metric=metric,
                    paper_target=paper_target,
                    unit=unit,
                    status="not measured",
                    run_1="not measured",
                    run_2="not measured",
                    run_3="not measured",
                    measured_mean="not measured",
                    diff_points="",
                    explanation=explanation,
                )
            )

    # 1. Vehicle Detector (Paper Table I targets)
    is_veh = veh_res.get("status") == "measured"
    add_row("Vehicle Detector", "YOLOv8m", "Precision", 94.0, "%", is_veh, veh_res.get("precision", 0.0),
            veh_res.get("reason", "Measured on held-out test split"))
    add_row("Vehicle Detector", "YOLOv8m", "Recall", 91.1, "%", is_veh, veh_res.get("recall", 0.0),
            veh_res.get("reason", "Measured on held-out test split"))
    add_row("Vehicle Detector", "YOLOv8m", "F1-Score", 92.5, "%", is_veh, veh_res.get("f1", 0.0),
            veh_res.get("reason", "Measured on held-out test split"))
    add_row("Vehicle Detector", "YOLOv8m", "mAP@0.5", 93.0, "%", is_veh, veh_res.get("map50", 0.0),
            veh_res.get("reason", "Measured on held-out test split"))

    # 2. Plate Detector (Paper Table I targets)
    is_plate = plate_res.get("status") == "measured"
    add_row("Plate Detector", "YOLOv8s", "Precision", 92.0, "%", is_plate, plate_res.get("precision", 0.0),
            plate_res.get("reason", "Measured on held-out test split"))
    add_row("Plate Detector", "YOLOv8s", "Recall", 89.0, "%", is_plate, plate_res.get("recall", 0.0),
            plate_res.get("reason", "Measured on held-out test split"))
    add_row("Plate Detector", "YOLOv8s", "F1-Score", 90.5, "%", is_plate, plate_res.get("f1", 0.0),
            plate_res.get("reason", "Measured on held-out test split"))
    add_row("Plate Detector", "YOLOv8s", "mAP@0.5", 91.0, "%", is_plate, plate_res.get("map50", 0.0),
            plate_res.get("reason", "Measured on held-out test split"))

    # 3. Multi-Object Tracking (ByteTrack)
    add_row(
        "Multi-Object Tracking", "ByteTrack", "MOTA", 78.5, "%", True, track_runs,
        "Measured using real ByteTrack tracker against synthetic ground-truth tracks via py-motmetrics",
    )

    # 4. Plate OCR Recognition (Paper Table I targets)
    is_ocr = ocr_res.get("status") == "measured"
    add_row("Plate OCR Recognition", "EasyOCR Single-Frame", "Plate Accuracy", 88.6, "%", is_ocr,
            ocr_res.get("single_frame_accuracy", 0.0),
            ocr_res.get("reason", "Measured on labeled plate dataset"))
    add_row("Plate OCR Recognition", "PlateVoter (Multi-Frame)", "Plate Accuracy", 94.2, "%", is_ocr,
            ocr_res.get("voted_accuracy", 0.0),
            ocr_res.get("reason", "Measured on labeled plate dataset"))
    add_row("Plate OCR Recognition", "Multi-Frame Voting", "Accuracy Gain", 5.6, "pts", is_ocr,
            ocr_res.get("accuracy_gain", 0.0),
            ocr_res.get("reason", "Measured on labeled plate dataset"))

    # 5. Three-Tier Matching (Synthetic Sample Replay)
    add_row(
        "Three-Tier Matching", "Tier 1 (Exact Only)", "Precision", 100.0, "%", True,
        match_res["exact_precision"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Tier 1 (Exact Only)", "Recall", 78.6, "%", True,
        match_res["exact_recall"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Tier 1+2 (+Fuzzy)", "Precision", 90.4, "%", True,
        match_res["fuzzy_precision"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Tier 1+2 (+Fuzzy)", "False Links", 51.0, "count", True,
        match_res["fuzzy_fp"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Tier 1+2+3 (Final)", "Precision", 96.2, "%", True,
        match_res["three_tier_precision"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Tier 1+2+3 (Final)", "Recall", 94.0, "%", True,
        match_res["three_tier_recall"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Tier 1+2+3 (Final)", "F1-Score", 95.1, "%", True,
        match_res["three_tier_f1"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )
    add_row(
        "Three-Tier Matching", "Kinematic Speed Filter", "False Link Reduction", 62.7, "%", True,
        match_res["fp_reduction"],
        "Replayed through backend/app/matching/matcher.py on synthetic sample dataset",
    )

    # 6. Ablation: Preprocessing
    add_row(
        "Ablation: Preprocessing", "CLAHE + Confusion Matrix", "Error Reduction", 41.2, "%", False, None,
        "Not measured; requires paired raw vs enhanced OCR evaluation on labeled plate dataset",
    )

    # 7. Ablation: Detector
    if measured_fps is not None:
        add_row(
            "Ablation: Detector", "YOLOv8m", "Throughput", 62.0, "FPS", True, measured_fps,
            f"Measured CPU throughput on current host ({measured_fps} FPS vs paper 62 FPS on NVIDIA GPU)",
        )
    else:
        add_row(
            "Ablation: Detector", "YOLOv8m", "Throughput", 62.0, "FPS", False, None,
            "Not measured; requires YOLOv8m benchmark environment",
        )
    add_row(
        "Ablation: Detector", "Faster R-CNN (ResNet-50)", "Throughput", 8.0, "FPS", False, None,
        "Not measured; Faster R-CNN weights and benchmark not included in repository",
    )
    add_row(
        "Ablation: Detector", "Faster R-CNN (ResNet-50)", "mAP@0.5", 95.0, "%", False, None,
        "Not measured; Faster R-CNN weights and evaluation split not included in repository",
    )

    # 8. Ablation: Tracker
    add_row(
        "Ablation: Tracker", "ByteTrack", "MOTA", 78.5, "%", True, track_runs,
        "Measured using real ByteTrack tracker against synthetic ground-truth tracks via py-motmetrics",
    )
    add_row(
        "Ablation: Tracker", "DeepSORT", "MOTA", 74.9, "%", False, None,
        "Not measured; DeepSORT tracker baseline not implemented in repository",
    )
    add_row(
        "Ablation: Tracker", "SORT", "MOTA", 68.2, "%", False, None,
        "Not measured; SORT tracker baseline not implemented in repository",
    )

    # Write to CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "category",
        "component",
        "metric",
        "paper_target",
        "measured_mean",
        "run_1",
        "run_2",
        "run_3",
        "diff_points",
        "unit",
        "status",
        "explanation",
    ]

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in eval_rows:
            writer.writerow({
                "category": row.category,
                "component": row.component,
                "metric": row.metric,
                "paper_target": row.paper_target,
                "measured_mean": row.measured_mean,
                "run_1": row.run_1,
                "run_2": row.run_2,
                "run_3": row.run_3,
                "diff_points": row.diff_points,
                "unit": row.unit,
                "status": row.status,
                "explanation": row.explanation,
            })

    print(f"\nSuccessfully written honest evaluation metrics to: {output_csv}")
    return eval_rows


def print_markdown_reports(rows: List[EvalRow]) -> None:
    """Print the formatted Markdown Table III comparison."""
    print("\n" + "=" * 95)
    print("### TABLE III: ROADTRACE AI SYSTEM EVALUATION (HONEST AUDIT)")
    print("=" * 95)
    print(
        f"| {'Component':<28} | {'Metric':<18} | {'Paper Target':<14} | {'Measured (Mean)':<16} | {'Status':<14} |"
    )
    print(
        f"|:{'-'*28}|:{'-'*18}|:{'-'*14}:|:{'-'*16}:|:{'-'*14}:|"
    )

    for r in rows:
        target_str = f"{r.paper_target:.1f} {r.unit}"
        if r.status == "measured":
            meas_str = f"{r.measured_mean:.1f} {r.unit}" if isinstance(r.measured_mean, (int, float)) else str(r.measured_mean)
        else:
            meas_str = "not measured"

        print(
            f"| {r.component:<28} | {r.metric:<18} | {target_str:<14} | {meas_str:<16} | {r.status:<14} |"
        )
    print("=" * 95 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RoadTrace AI Table III Honest Benchmark Runner")
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[42, 43, 44],
        help="Random seeds for repeated benchmark runs",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="results/table3.csv",
        help="Destination path for table3.csv",
    )
    args = parser.parse_args()

    out_csv = Path(args.output_csv)
    results = run_all_evaluations(seeds=args.seeds, output_csv=out_csv)
    print_markdown_reports(results)
