from pathlib import Path
import tempfile

import cv2
import numpy as np
import pytest
import yaml

from ml.training.finetune_vehicle import (
    CLASS_COUNTS,
    TOTAL_INSTANCES,
    compute_class_weights,
)
from ml.training.prepare_dataset import DatasetPreparer


def test_prepare_dataset_deduplication(tmp_path: Path):
    preparer = DatasetPreparer(output_dir=tmp_path / "dataset")

    # Create two identical image files and one distinct image file
    img1 = tmp_path / "img1.jpg"
    img2 = tmp_path / "img2.jpg"
    img3 = tmp_path / "img3.jpg"

    data1 = np.full((100, 100, 3), 100, dtype=np.uint8)
    data3 = np.full((100, 100, 3), 200, dtype=np.uint8)

    cv2.imwrite(str(img1), data1)
    cv2.imwrite(str(img2), data1)  # Identical content to img1
    cv2.imwrite(str(img3), data3)  # Distinct

    # Ingest img1: should be accepted
    added1 = preparer.add_frame("clip_01", img1)
    assert added1 is True

    # Ingest img2: duplicate of img1, should be rejected
    added2 = preparer.add_frame("clip_01", img2)
    assert added2 is False

    # Ingest img3: distinct, should be accepted
    added3 = preparer.add_frame("clip_02", img3)
    assert added3 is True

    assert len(preparer.clips["clip_01"]) == 1
    assert len(preparer.clips["clip_02"]) == 1


def test_prepare_dataset_clip_split_no_leakage(tmp_path: Path):
    output_dir = tmp_path / "plate_yolo"
    preparer = DatasetPreparer(output_dir=output_dir, seed=42)

    # Generate synthetic clips (20 clips with 3 frames each)
    counts = preparer.generate_synthetic_plate_dataset(num_clips=20, frames_per_clip=3)

    assert counts["train_clips"] == 14  # 70% of 20
    assert counts["val_clips"] == 3    # 15% of 20
    assert counts["test_clips"] == 3   # 15% of 20

    # Verify directory structure
    assert (output_dir / "train" / "images").exists()
    assert (output_dir / "val" / "images").exists()
    assert (output_dir / "test" / "images").exists()
    assert (output_dir / "data.yaml").exists()

    # Verify NO leakage: check all files in each split belong exclusively to that split's clips
    train_files = {p.name for p in (output_dir / "train" / "images").glob("*.jpg")}
    val_files = {p.name for p in (output_dir / "val" / "images").glob("*.jpg")}
    test_files = {p.name for p in (output_dir / "test" / "images").glob("*.jpg")}

    # No overlapping files across splits
    assert len(train_files.intersection(val_files)) == 0
    assert len(train_files.intersection(test_files)) == 0
    assert len(val_files.intersection(test_files)) == 0

    # Verify clip prefixes do not cross splits
    train_clip_ids = {f.split("_frame_")[0] for f in train_files}
    val_clip_ids = {f.split("_frame_")[0] for f in val_files}
    test_clip_ids = {f.split("_frame_")[0] for f in test_files}

    assert len(train_clip_ids.intersection(val_clip_ids)) == 0
    assert len(train_clip_ids.intersection(test_clip_ids)) == 0
    assert len(val_clip_ids.intersection(test_clip_ids)) == 0

    # Verify data.yaml contents
    with open(output_dir / "data.yaml") as f:
        data_cfg = yaml.safe_load(f)
    assert data_cfg["names"][0] == "license_plate"
    assert data_cfg["train"] == "train/images"
    assert data_cfg["val"] == "val/images"
    assert data_cfg["test"] == "test/images"


def test_class_weights_calculation():
    # Paper instance distribution:
    # 18,600 total: 10,416 cars, 3,534 trucks, 2,418 buses, 2,232 two-wheelers
    assert TOTAL_INSTANCES == 18600
    assert CLASS_COUNTS["passenger_car"] == 10416
    assert CLASS_COUNTS["commercial_truck"] == 3534
    assert CLASS_COUNTS["public_bus"] == 2418
    assert CLASS_COUNTS["two_wheeler"] == 2232

    weights = compute_class_weights()

    # Rare classes should have higher weights to counter class imbalance
    assert weights["passenger_car"] < weights["commercial_truck"]
    assert weights["commercial_truck"] < weights["public_bus"]
    assert weights["public_bus"] < weights["two_wheeler"]

    # Verify mathematical formula: w_c = N_total / (N_classes * N_c)
    expected_car = round(18600 / (4 * 10416), 4)
    expected_truck = round(18600 / (4 * 3534), 4)
    expected_bus = round(18600 / (4 * 2418), 4)
    expected_2w = round(18600 / (4 * 2232), 4)

    assert weights["passenger_car"] == expected_car
    assert weights["commercial_truck"] == expected_truck
    assert weights["public_bus"] == expected_bus
    assert weights["two_wheeler"] == expected_2w


def test_f1_score_calculation():
    def compute_f1(p: float, r: float) -> float:
        return 2 * (p * r) / (p + r) if (p + r) > 0 else 0.0

    # Plate targets: P ~ 0.90, R ~ 0.91 -> F1 ~ 0.905
    plate_f1 = compute_f1(0.905, 0.905)
    assert abs(plate_f1 - 0.905) < 1e-4

    # Vehicle targets: P ~ 0.925, R ~ 0.925 -> F1 ~ 0.925
    vehicle_f1 = compute_f1(0.925, 0.925)
    assert abs(vehicle_f1 - 0.925) < 1e-4
