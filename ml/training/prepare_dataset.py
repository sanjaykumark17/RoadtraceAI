import argparse
import hashlib
from pathlib import Path
import random
import shutil
import sys
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
import yaml


class DatasetPreparer:
    """Merges and splits license plate and vehicle datasets by video clip (70/15/15)."""

    def __init__(
        self,
        output_dir: Path,
        seed: int = 42,
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
    ):
        self.output_dir = Path(output_dir)
        self.seed = seed
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio

        # Clip-to-frames map: clip_id -> list of (image_path, label_path)
        self.clips: Dict[str, List[Tuple[Path, Optional[Path]]]] = {}
        self.seen_hashes: Set[str] = set()

    @staticmethod
    def compute_image_hash(image_path: Path) -> str:
        """Compute MD5 hash of image content for deduplication."""
        hasher = hashlib.md5()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def add_frame(
        self,
        clip_id: str,
        image_path: Path,
        label_path: Optional[Path] = None,
    ) -> bool:
        """Add frame if not a duplicate. Returns True if added."""
        try:
            img_hash = self.compute_image_hash(image_path)
        except Exception:
            return False

        if img_hash in self.seen_hashes:
            return False

        self.seen_hashes.add(img_hash)
        if clip_id not in self.clips:
            self.clips[clip_id] = []
        self.clips[clip_id].append((image_path, label_path))
        return True

    def extract_clip_id(self, file_path: Path) -> str:
        """Extract clip ID from file name or directory name.

        Convention: {camera_or_clip_id}_frame_{num}.jpg or folder/clip_id/frame.jpg
        """
        stem = file_path.stem
        if "_frame" in stem:
            return stem.split("_frame")[0]
        if "_" in stem:
            return stem.rsplit("_", 1)[0]
        return file_path.parent.name

    def ingest_directory(
        self,
        source_dir: Path,
        default_clip_prefix: str = "clip",
    ) -> int:
        """Ingest YOLO-formatted directory (images/ and labels/ subdirs)."""
        source_dir = Path(source_dir)
        img_dir = source_dir / "images" if (source_dir / "images").exists() else source_dir
        label_dir = source_dir / "labels" if (source_dir / "labels").exists() else None

        count = 0
        for img_path in img_dir.glob("*.[jJ][pP][gG]"):
            clip_id = self.extract_clip_id(img_path)
            if not clip_id:
                clip_id = f"{default_clip_prefix}_{count // 30}"

            lbl_path = None
            if label_dir:
                candidate = label_dir / f"{img_path.stem}.txt"
                if candidate.exists():
                    lbl_path = candidate

            if self.add_frame(clip_id, img_path, lbl_path):
                count += 1
        return count

    def split_and_export(
        self,
        classes: List[str] = ["license_plate"],
    ) -> Dict[str, int]:
        """Split dataset 70/15/15 BY VIDEO CLIP and write YOLO dataset."""
        clip_ids = sorted(list(self.clips.keys()))
        random.seed(self.seed)
        random.shuffle(clip_ids)

        total_clips = len(clip_ids)
        n_train = int(round(total_clips * self.train_ratio))
        n_val = int(round(total_clips * self.val_ratio))

        train_clips = set(clip_ids[:n_train])
        val_clips = set(clip_ids[n_train : n_train + n_val])
        test_clips = set(clip_ids[n_train + n_val :])

        splits = {
            "train": train_clips,
            "val": val_clips,
            "test": test_clips,
        }

        counts = {
            "train": 0,
            "val": 0,
            "test": 0,
            "train_clips": len(train_clips),
            "val_clips": len(val_clips),
            "test_clips": len(test_clips),
        }

        for split_name, assigned_clips in splits.items():
            split_img_dir = self.output_dir / split_name / "images"
            split_lbl_dir = self.output_dir / split_name / "labels"
            split_img_dir.mkdir(parents=True, exist_ok=True)
            split_lbl_dir.mkdir(parents=True, exist_ok=True)

            for cid in assigned_clips:
                for img_path, lbl_path in self.clips[cid]:
                    dest_img = split_img_dir / img_path.name
                    shutil.copy2(img_path, dest_img)
                    if lbl_path and lbl_path.exists():
                        dest_lbl = split_lbl_dir / lbl_path.name
                        shutil.copy2(lbl_path, dest_lbl)
                    else:
                        (split_lbl_dir / f"{img_path.stem}.txt").touch()
                    counts[split_name] += 1

        # Write data.yaml
        yaml_content = {
            "path": str(self.output_dir.resolve()).replace("\\", "/"),
            "train": "train/images",
            "val": "val/images",
            "test": "test/images",
            "names": {i: name for i, name in enumerate(classes)},
        }
        with open(self.output_dir / "data.yaml", "w") as f:
            yaml.dump(yaml_content, f, sort_keys=False)

        return counts

    def generate_synthetic_plate_dataset(
        self,
        num_clips: int = 100,
        frames_per_clip: int = 3,
    ) -> Dict[str, int]:
        """Generate synthetic dataset with day/night/rain/shadow variations."""
        scratch_dir = self.output_dir / "_temp_raw"
        scratch_img = scratch_dir / "images"
        scratch_lbl = scratch_dir / "labels"
        scratch_img.mkdir(parents=True, exist_ok=True)
        scratch_lbl.mkdir(parents=True, exist_ok=True)

        conditions = ["day", "night_headlight", "rain", "shadow"]

        for c_idx in range(num_clips):
            clip_id = f"clip_{c_idx:04d}"
            cond = conditions[c_idx % len(conditions)]

            for f_idx in range(frames_per_clip):
                # Unique random background noise and camera marker per clip & frame
                if cond == "night_headlight":
                    frame = np.full((720, 1280, 3), 30, dtype=np.uint8)
                    cv2.circle(frame, (500 + (c_idx * 17) % 300, 360), 120, (255, 255, 200), -1)
                elif cond == "rain":
                    frame = np.full((720, 1280, 3), 110, dtype=np.uint8)
                    for r_i in range(30):
                        rx = (c_idx * 31 + r_i * 41) % 1270
                        ry = (r_i * 23) % 700
                        cv2.line(frame, (rx, ry), (rx + 2, ry + 15), (200, 200, 200), 1)
                elif cond == "shadow":
                    frame = np.full((720, 1280, 3), 160, dtype=np.uint8)
                    cv2.rectangle(frame, (0, 0), (640, 720), (70, 70, 70), -1)
                else:
                    frame = np.full((720, 1280, 3), 150, dtype=np.uint8)

                # Watermark frame with unique camera/clip index to simulate distinct sensor feeds
                cv2.putText(
                    frame,
                    f"CAM_{c_idx:04d}_{f_idx:03d}",
                    (30, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (200, 200, 200),
                    1,
                )

                # Simulated vehicle + license plate
                vx = 200 + (c_idx * 23 + f_idx * 7) % 600
                vy = 280
                vw, vh = 320, 160
                cv2.rectangle(frame, (vx, vy), (vx + vw, vy + vh), (80, 80, 80), -1)

                px, py, pw, ph = vx + 110, vy + 95, 100, 35
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (240, 240, 240), -1)
                cv2.putText(
                    frame,
                    f"TN{c_idx % 99:02d}AB{f_idx:04d}",
                    (px + 5, py + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (10, 10, 10),
                    1,
                )

                img_file = scratch_img / f"{clip_id}_frame_{f_idx:03d}.jpg"
                lbl_file = scratch_lbl / f"{clip_id}_frame_{f_idx:03d}.txt"

                cv2.imwrite(str(img_file), frame)

                # YOLO normalized bbox: class_id, x_center, y_center, width, height
                xc = (px + pw / 2.0) / 1280.0
                yc = (py + ph / 2.0) / 720.0
                nw = pw / 1280.0
                nh = ph / 720.0
                with open(lbl_file, "w") as lf:
                    lf.write(f"0 {xc:.6f} {yc:.6f} {nw:.6f} {nh:.6f}\n")

                self.add_frame(clip_id, img_file, lbl_file)

        counts = self.split_and_export(classes=["license_plate"])

        # Clean up scratch dir
        try:
            shutil.rmtree(scratch_dir)
        except Exception:
            pass

        return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare YOLO License Plate or Vehicle Dataset (70/15/15 Clip Split)")
    parser.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help="Directory containing real YOLO-format data (images/ and labels/ subdirectories or clip folders) to ingest",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="ml/data/plate_dataset",
        help="Destination directory for processed YOLO dataset",
    )
    parser.add_argument(
        "--classes",
        nargs="+",
        default=["license_plate"],
        help="Class names for data.yaml (default: license_plate)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Generate synthetic mock dataset for testing only (not for real model training)",
    )
    parser.add_argument(
        "--clips",
        type=int,
        default=60,
        help="Number of synthetic clips to generate in mock mode (test only)",
    )
    args = parser.parse_args()

    preparer = DatasetPreparer(output_dir=Path(args.output_dir))
    if args.mock:
        print(f"Generating synthetic mock dataset (testing only) with {args.clips} clips...")
        res = preparer.generate_synthetic_plate_dataset(num_clips=args.clips)
        print("Mock test dataset prepared successfully:", res)
    elif args.input_dir:
        input_path = Path(args.input_dir)
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_path}")
        print(f"Ingesting real dataset from {input_path}...")
        n_frames = preparer.ingest_directory(input_path)
        print(f"Ingested {n_frames} unique frames across {len(preparer.clips)} clips.")
        print("Splitting dataset 70/15/15 by video clip...")
        res = preparer.split_and_export(classes=args.classes)
        print("Real dataset prepared and split successfully:", res)
    else:
        print("Error: Specify either --input-dir <path> for real dataset ingest or --mock for test-only synthetic dataset.")
        sys.exit(1)
