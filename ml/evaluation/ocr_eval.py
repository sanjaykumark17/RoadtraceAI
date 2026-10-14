"""Evaluate Plate OCR & Multi-Frame Voting using real EasyOCR and PlateVoter.

Runs on a labeled directory of license plate crop images.
If the labeled image folder is absent, prints 'not measured' with the explanation.
"""

import argparse
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parents[2] / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

import cv2

from app.inference.plate_ocr import (
    OCRReaderSingleton,
    PlateVoter,
    normalize_plate,
    read_plate_text,
)


def evaluate_ocr(
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Measure single-frame vs voted plate-level accuracy on a real labeled image dataset.

    Paper targets:
      Single-frame accuracy: ~88.6%
      Voted plate accuracy : ~94.2%
      Accuracy gain        : +5.6 pts
    """
    print("=" * 60)
    print(" ROADTRACE AI - PLATE OCR EVALUATION (SINGLE-FRAME VS VOTED)")
    print("=" * 60)

    if not data_dir:
        print("Status: not measured")
        print("Reason: No labeled OCR image folder specified. Run with --data-dir <path>.")
        print("=" * 60)
        return {
            "status": "not measured",
            "single_frame_accuracy": None,
            "voted_accuracy": None,
            "accuracy_gain": None,
            "total_frames": 0,
            "total_tracks": 0,
            "reason": "No labeled OCR image directory specified",
        }

    dataset_path = Path(data_dir).resolve()
    if not dataset_path.exists() or not dataset_path.is_dir():
        print("Status: not measured")
        print(f"Reason: Labeled OCR image folder not found at {dataset_path}.")
        print("=" * 60)
        return {
            "status": "not measured",
            "single_frame_accuracy": None,
            "voted_accuracy": None,
            "accuracy_gain": None,
            "total_frames": 0,
            "total_tracks": 0,
            "reason": f"Directory not found: {dataset_path}",
        }

    # Find image files
    image_files = sorted(
        [
            p
            for p in dataset_path.rglob("*")
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
        ]
    )

    if not image_files:
        print("Status: not measured")
        print(f"Reason: No image files found in {dataset_path}.")
        print("=" * 60)
        return {
            "status": "not measured",
            "single_frame_accuracy": None,
            "voted_accuracy": None,
            "accuracy_gain": None,
            "total_frames": 0,
            "total_tracks": 0,
            "reason": f"No image files found in {dataset_path}",
        }

    print(f"Found {len(image_files)} plate images in {dataset_path}")
    print("Initializing EasyOCR reader...")
    reader = OCRReaderSingleton().reader

    # Group images into tracks by subdirectory or naming convention
    # Format: folder/track_id/frame.jpg OR folder/{plate}_{idx}.jpg OR label txt file
    tracks: Dict[str, List[Path]] = {}
    track_ground_truth: Dict[str, str] = {}

    for img_path in image_files:
        # Check for adjacent .txt ground truth label
        lbl_file = img_path.with_suffix(".txt")
        if lbl_file.exists():
            with open(lbl_file, "r", encoding="utf-8") as f:
                true_plate = f.read().strip().upper()
        else:
            # Fallback: parse plate from filename prefix before '_'
            stem = img_path.stem
            true_plate = stem.split("_")[0].upper()

        if img_path.parent != dataset_path:
            track_id = img_path.parent.name
        else:
            track_id = true_plate

        if track_id not in tracks:
            tracks[track_id] = []
            track_ground_truth[track_id] = true_plate

        tracks[track_id].append(img_path)

    total_single_frames = 0
    correct_single_frames = 0
    total_tracks = 0
    correct_voted_tracks = 0

    for track_idx, (track_id, img_list) in enumerate(tracks.items()):
        true_plate = track_ground_truth[track_id]
        voter = PlateVoter(track_id=track_idx)

        for img_p in img_list:
            img = cv2.imread(str(img_p))
            if img is None:
                continue

            total_single_frames += 1
            raw_text, conf = read_plate_text(img, reader=reader)
            norm = normalize_plate(raw_text)

            if norm == true_plate:
                correct_single_frames += 1

            if norm:
                voter.add_read(norm, confidence=conf)

        total_tracks += 1
        voted_res = voter.finalize()
        if voted_res and voted_res.plate_number == true_plate:
            correct_voted_tracks += 1

    single_frame_acc = (
        (correct_single_frames / total_single_frames * 100.0)
        if total_single_frames > 0
        else 0.0
    )
    voted_acc = (
        (correct_voted_tracks / total_tracks * 100.0)
        if total_tracks > 0
        else 0.0
    )
    gain = voted_acc - single_frame_acc

    print(f"Total Single Frames Evaluated : {total_single_frames}")
    print(f"Total Vehicle Tracks Evaluated: {total_tracks}")
    print("-" * 60)
    print(f"Single-Frame Accuracy : {single_frame_acc:.1f}%  (Paper Target: ~88.6%)")
    print(f"Voted Plate Accuracy  : {voted_acc:.1f}%  (Paper Target: ~94.2%)")
    print(f"Accuracy Gain from Voting: +{gain:.1f}%")
    print("=" * 60)

    return {
        "status": "measured",
        "single_frame_accuracy": round(single_frame_acc, 2),
        "voted_accuracy": round(voted_acc, 2),
        "accuracy_gain": round(gain, 2),
        "total_frames": total_single_frames,
        "total_tracks": total_tracks,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Plate OCR & Multi-Frame Voting")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Directory containing labeled plate crop images",
    )
    args = parser.parse_args()

    evaluate_ocr(data_dir=args.data_dir)
