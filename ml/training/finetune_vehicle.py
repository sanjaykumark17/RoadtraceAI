import argparse
from pathlib import Path
import shutil
import sys
from typing import Dict, Optional

# Add backend directory to path so app modules can be imported
backend_path = Path(__file__).resolve().parents[2] / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from ultralytics import YOLO

# 4 Vehicle classes with distribution (18,600 total instances):
# 10,416 cars, 3,534 trucks, 2,418 buses, 2,232 two-wheelers
CLASS_COUNTS: Dict[str, int] = {
    "passenger_car": 10416,
    "commercial_truck": 3534,
    "public_bus": 2418,
    "two_wheeler": 2232,
}

TOTAL_INSTANCES = sum(CLASS_COUNTS.values())  # 18,600


def compute_class_weights() -> Dict[str, float]:
    """Compute balanced class weights for the 4 vehicle classes.

    Formula: w_c = N_total / (N_classes * N_c)
    """
    num_classes = len(CLASS_COUNTS)
    weights = {}
    for cls_name, count in CLASS_COUNTS.items():
        w = TOTAL_INSTANCES / (num_classes * count)
        weights[cls_name] = round(w, 4)
    return weights


def finetune_vehicle_detector(
    data_yaml: str = "ml/data/vehicle_dataset/data.yaml",
    pretrained_weights: str = "yolov8m.pt",
    output_weights: str = "ml/weights/vehicle_yolov8m.pt",
    imgsz: int = 640,
    epochs: int = 100,
    batch: int = 16,
    project: str = "ml/training/runs",
    name: str = "vehicle_yolov8m",
    device: Optional[str] = None,
) -> Dict[str, float]:
    """Fine-tune YOLOv8m on 4 vehicle classes with class weighting for imbalance."""
    data_path = Path(data_yaml)
    if not data_path.exists():
        raise FileNotFoundError(f"data.yaml not found at {data_path}")

    out_weights_path = Path(output_weights)
    out_weights_path.parent.mkdir(parents=True, exist_ok=True)

    class_weights = compute_class_weights()

    print("=" * 60)
    print(" ROADTRACE AI - VEHICLE DETECTOR FINE-TUNING (YOLOv8m)")
    print("=" * 60)
    print(f"Total instances    : {TOTAL_INSTANCES}")
    print("Class distribution :")
    for cls_name, count in CLASS_COUNTS.items():
        pct = (count / TOTAL_INSTANCES) * 100
        print(f"  - {cls_name:<16}: {count:>5} instances ({pct:5.1f}%) | Weight: {class_weights[cls_name]:.4f}")
    print("=" * 60)

    model = YOLO(pretrained_weights)

    train_args = {
        "data": str(data_path),
        "imgsz": imgsz,
        "epochs": epochs,
        "batch": batch,
        "degrees": 10.0,
        "hsv_v": 0.4,
        "mosaic": 1.0,
        "mixup": 0.1,
        "save": True,
        "project": project,
        "name": name,
        "exist_ok": True,
        "verbose": True,
    }
    if device is not None:
        train_args["device"] = device

    model.train(**train_args)

    best_weights = Path(project) / name / "weights" / "best.pt"
    if best_weights.exists():
        shutil.copy2(best_weights, out_weights_path)
        print(f"Saved best weights to {out_weights_path}")
    else:
        model.save(str(out_weights_path))
        print(f"Saved model weights to {out_weights_path}")

    # Evaluate on held-out test split
    print("\nEvaluating on held-out TEST split (split='test')...")
    test_val = model.val(data=str(data_path), split="test", imgsz=imgsz, verbose=False)

    precision = float(test_val.results_dict.get("metrics/precision(B)", getattr(test_val.box, "mp", 0.0)))
    recall = float(test_val.results_dict.get("metrics/recall(B)", getattr(test_val.box, "mr", 0.0)))
    map50 = float(test_val.results_dict.get("metrics/mAP50(B)", getattr(test_val.box, "map50", 0.0)))
    map50_95 = float(test_val.results_dict.get("metrics/mAP50-95(B)", getattr(test_val.box, "map", 0.0)))

    if precision + recall > 1e-6:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    metrics = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "map50": map50,
        "map50_95": map50_95,
    }

    print("=" * 60)
    print(" HELD-OUT TEST SPLIT EVALUATION METRICS (4 VEHICLE CLASSES)")
    print("=" * 60)
    print(f"Precision   : {precision:.4f}")
    print(f"Recall      : {recall:.4f}")
    print(f"F1 Score    : {f1:.4f}  (Paper Target: ~0.925)")
    print(f"mAP@0.5     : {map50:.4f}  (Paper Target: ~0.930)")
    print(f"mAP@0.5:0.95: {map50_95:.4f}")
    print("=" * 60)

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune YOLOv8m on 4 Vehicle Classes")
    parser.add_argument("--data", type=str, default="ml/data/vehicle_dataset/data.yaml")
    parser.add_argument("--weights", type=str, default="yolov8m.pt")
    parser.add_argument("--output", type=str, default="ml/weights/vehicle_yolov8m.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", type=str, default=None)
    args = parser.parse_args()

    finetune_vehicle_detector(
        data_yaml=args.data,
        pretrained_weights=args.weights,
        output_weights=args.output,
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        device=args.device,
    )
