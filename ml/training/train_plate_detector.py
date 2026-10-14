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



def train_plate_detector(
    data_yaml: str = "ml/data/plate_dataset/data.yaml",
    pretrained_weights: str = "yolov8s.pt",
    output_weights: str = "ml/weights/plate_yolov8s.pt",
    imgsz: int = 640,
    epochs: int = 100,
    batch: int = 16,
    project: str = "ml/training/runs",
    name: str = "plate_yolov8s",
    device: Optional[str] = None,
) -> Dict[str, float]:
    """Fine-tune YOLOv8s on license_plate dataset with angle, blur, and lighting augmentations.

    Returns:
        Dict with measured precision, recall, f1, map50 on held-out test split.
    """
    data_path = Path(data_yaml)
    if not data_path.exists():
        raise FileNotFoundError(f"data.yaml not found at {data_path}")

    out_weights_path = Path(output_weights)
    out_weights_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" ROADTRACE AI - LICENSE PLATE DETECTOR TRAINING (YOLOv8s)")
    print("=" * 60)
    print(f"Data config        : {data_yaml}")
    print(f"Pretrained weights : {pretrained_weights}")
    print(f"Image Size         : {imgsz}")
    print(f"Epochs             : {epochs}")
    print(f"Batch Size         : {batch}")
    print("Augmentations      : angle (degrees=15), brightness (hsv_v=0.4), rain/noise (mosaic=1.0, mixup=0.15)")
    print("=" * 60)

    model = YOLO(pretrained_weights)

    # Train model with specific domain augmentations:
    # - Angle / perspective: degrees=15.0, shear=2.0
    # - Brightness / headlight bloom: hsv_v=0.4, hsv_s=0.7
    # - Motion blur & rain: mosaic=1.0, mixup=0.15
    train_args = {
        "data": str(data_path),
        "imgsz": imgsz,
        "epochs": epochs,
        "batch": batch,
        "degrees": 15.0,
        "shear": 2.0,
        "perspective": 0.0005,
        "hsv_v": 0.4,
        "hsv_s": 0.7,
        "mosaic": 1.0,
        "mixup": 0.15,
        "save": True,
        "project": project,
        "name": name,
        "exist_ok": True,
        "verbose": True,
    }
    if device is not None:
        train_args["device"] = device

    model.train(**train_args)

    # Save best weights to target destination
    best_weights = Path(project) / name / "weights" / "best.pt"
    if best_weights.exists():
        shutil.copy2(best_weights, out_weights_path)
        print(f"Saved best weights to {out_weights_path}")
    else:
        # Fallback to model weights
        model.save(str(out_weights_path))
        print(f"Saved model weights to {out_weights_path}")

    # Evaluate on held-out test split
    print("\nEvaluating on held-out TEST split (split='test')...")
    test_val = model.val(data=str(data_path), split="test", imgsz=imgsz, verbose=False)

    precision = float(test_val.results_dict.get("metrics/precision(B)", getattr(test_val.box, "mp", 0.0)))
    recall = float(test_val.results_dict.get("metrics/recall(B)", getattr(test_val.box, "mr", 0.0)))
    map50 = float(test_val.results_dict.get("metrics/mAP50(B)", getattr(test_val.box, "map50", 0.0)))
    map50_95 = float(test_val.results_dict.get("metrics/mAP50-95(B)", getattr(test_val.box, "map", 0.0)))

    # F1 score calculation
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
    print(" HELD-OUT TEST SPLIT EVALUATION METRICS (LICENSE PLATE)")
    print("=" * 60)
    print(f"Precision   : {precision:.4f}")
    print(f"Recall      : {recall:.4f}")
    print(f"F1 Score    : {f1:.4f}  (Paper Target: ~0.905)")
    print(f"mAP@0.5     : {map50:.4f}  (Paper Target: ~0.910)")
    print(f"mAP@0.5:0.95: {map50_95:.4f}")
    print("=" * 60)

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train License Plate YOLOv8s Detector")
    parser.add_argument("--data", type=str, default="ml/data/plate_dataset/data.yaml")
    parser.add_argument("--weights", type=str, default="yolov8s.pt")
    parser.add_argument("--output", type=str, default="ml/weights/plate_yolov8s.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", type=str, default=None)
    args = parser.parse_args()

    train_plate_detector(
        data_yaml=args.data,
        pretrained_weights=args.weights,
        output_weights=args.output,
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        device=args.device,
    )
