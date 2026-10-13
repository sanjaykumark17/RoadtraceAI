from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import easyocr
import numpy as np
import torch
from ultralytics import YOLO

from app.core.config import settings
from app.inference.preprocess import enhance_plate, is_blurry

# Positional confusion matrices for Indian format: AA 00 A(A) 0000
# In LETTER positions map digits to letters:
DIGIT_TO_LETTER: Dict[str, str] = {
    "0": "O",
    "1": "I",
    "8": "B",
    "5": "S",
    "2": "Z",
    "6": "G",
}

# In DIGIT positions map letters to digits:
LETTER_TO_DIGIT: Dict[str, str] = {
    "O": "0",
    "I": "1",
    "B": "8",
    "S": "5",
    "Z": "2",
    "G": "6",
    "D": "0",
}

OCR_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def normalize_plate(raw_text: str) -> Optional[str]:
    """Normalize raw OCR text using positional character confusion matrix.

    Indian format: AA 00 A(A) 0000
    - Length 9 (1 series letter): AA 00 A 0000
        Letters: indices 0, 1, 4
        Digits: indices 2, 3, 5, 6, 7, 8
    - Length 10 (2 series letters): AA 00 AA 0000
        Letters: indices 0, 1, 4, 5
        Digits: indices 2, 3, 6, 7, 8, 9

    Validates against PLATE_REGEX; returns None if invalid.
    """
    if not raw_text:
        return None

    # Uppercase and strip spaces, hyphens, and non-alphanumeric characters
    cleaned = "".join(c for c in str(raw_text).upper() if c.isalnum())
    length = len(cleaned)
    if length not in (9, 10):
        return None

    chars = list(cleaned)

    if length == 10:
        letter_indices = (0, 1, 4, 5)
        digit_indices = (2, 3, 6, 7, 8, 9)
    else:  # length == 9
        letter_indices = (0, 1, 4)
        digit_indices = (2, 3, 5, 6, 7, 8)

    # 1. In letter positions, map confusing digits to letters
    for idx in letter_indices:
        ch = chars[idx]
        if ch in DIGIT_TO_LETTER:
            chars[idx] = DIGIT_TO_LETTER[ch]

    # 2. In digit positions, map confusing letters to digits
    for idx in digit_indices:
        ch = chars[idx]
        if ch in LETTER_TO_DIGIT:
            chars[idx] = LETTER_TO_DIGIT[ch]

    candidate = "".join(chars)

    # Validate with PLATE_REGEX
    pattern = re.compile(settings.plate_regex)
    if pattern.match(candidate):
        return candidate
    return None


class PlateDetectorSingleton:
    """Singleton for YOLOv8s license plate detector."""

    _instance: Optional["PlateDetectorSingleton"] = None
    _model: Optional[YOLO] = None

    def __new__(cls, *args, **kwargs) -> "PlateDetectorSingleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, weights: Optional[str] = None):
        if PlateDetectorSingleton._model is None:
            # Check custom plate weights first, then fallback to yolov8s.pt
            target_weights = weights
            if not target_weights:
                cand = Path("ml/weights/plate_yolov8s.pt")
                target_weights = str(cand) if cand.exists() else "yolov8s.pt"
            PlateDetectorSingleton._model = YOLO(target_weights)
        self.model = PlateDetectorSingleton._model

    @classmethod
    def set_model(cls, model: YOLO) -> None:
        cls._model = model
        if cls._instance is not None:
            cls._instance.model = model

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._model = None


class OCRReaderSingleton:
    """Singleton for EasyOCR Reader (loaded once)."""

    _instance: Optional["OCRReaderSingleton"] = None
    _reader: Optional[easyocr.Reader] = None

    def __new__(cls, *args, **kwargs) -> "OCRReaderSingleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, gpu: Optional[bool] = None):
        if OCRReaderSingleton._reader is None:
            if gpu is None:
                gpu = torch.cuda.is_available()
            OCRReaderSingleton._reader = easyocr.Reader(["en"], gpu=gpu)
        self.reader = OCRReaderSingleton._reader

    @classmethod
    def set_reader(cls, reader: easyocr.Reader) -> None:
        cls._reader = reader
        if cls._instance is not None:
            cls._instance.reader = reader

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._reader = None


def read_plate_text(
    plate_image: np.ndarray,
    reader: Optional[easyocr.Reader] = None,
) -> Tuple[str, float]:
    """Run EasyOCR with allowlist and return (joined_text, avg_confidence)."""
    if reader is None:
        reader = OCRReaderSingleton().reader

    # EasyOCR reading with allowlist
    results = reader.readtext(plate_image, allowlist=OCR_ALLOWLIST)
    if not results:
        return "", 0.0

    # Sort segments horizontally by bounding box top-left x coordinate
    segments = sorted(results, key=lambda s: s[0][0][0])
    raw_text = "".join(s[1] for s in segments)
    cleaned = raw_text.upper().replace(" ", "").replace("-", "")

    confidences = [float(s[2]) for s in segments]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return cleaned, float(avg_conf)


def process_vehicle_crop_for_plate(
    vehicle_crop: np.ndarray,
    plate_detector: Optional[YOLO] = None,
    ocr_reader: Optional[easyocr.Reader] = None,
    blur_threshold: Optional[float] = None,
) -> Tuple[Optional[str], float, Optional[np.ndarray]]:
    """Execute complete 5-step OCR pipeline on a tracked vehicle crop.

    Steps:
      1. Skip if is_blurry(vehicle_crop).
      2. Detect plate box with YOLOv8s; crop with 5% padding.
      3. enhance_plate(plate_crop).
      4. EasyOCR readtext on enhanced plate image.
      5. normalize_plate(raw_text).

    Returns:
        (normalized_plate_or_None, confidence, plate_crop)
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return None, 0.0, None

    # Step 1: Skip if blurry
    if is_blurry(vehicle_crop, tau=blur_threshold):
        return None, 0.0, None

    # Step 2: Detect plate box inside vehicle crop
    if plate_detector is None:
        plate_detector = PlateDetectorSingleton().model

    vh, vw = vehicle_crop.shape[:2]
    results = plate_detector(vehicle_crop, verbose=False)[0]

    plate_box = None
    best_conf = 0.0
    if results.boxes is not None and len(results.boxes) > 0:
        boxes_data = results.boxes.cpu().numpy()
        for b in boxes_data:
            score = float(b.conf[0])
            if score > best_conf:
                best_conf = score
                plate_box = tuple(float(x) for x in b.xyxy[0])

    if plate_box is not None:
        # Crop plate with 5% padding
        px1, py1, px2, py2 = plate_box
        pw = px2 - px1
        ph = py2 - py1
        pad_x = 0.05 * pw
        pad_y = 0.05 * ph

        cx1 = max(0, int(px1 - pad_x))
        cy1 = max(0, int(py1 - pad_y))
        cx2 = min(vw, int(px2 + pad_x))
        cy2 = min(vh, int(py2 + pad_y))

        plate_crop = vehicle_crop[cy1:cy2, cx1:cx2]
    else:
        # Fallback: bottom 40% of vehicle crop where plates are commonly mounted
        plate_crop = vehicle_crop[int(vh * 0.60) :, :]

    if plate_crop is None or plate_crop.size == 0:
        return None, 0.0, None

    # Step 3: Enhance plate (Grayscale -> CLAHE -> Bilateral -> Otsu)
    enhanced_gray, binary = enhance_plate(plate_crop)

    # Step 4: EasyOCR read text
    raw_text, ocr_conf = read_plate_text(enhanced_gray, reader=ocr_reader)
    if not raw_text:
        # Retry with binary image
        raw_text, ocr_conf = read_plate_text(binary, reader=ocr_reader)

    # Step 5: Normalize plate text with positional confusion matrix
    normalized = normalize_plate(raw_text)

    return normalized, ocr_conf, plate_crop


@dataclass
class VoteResult:
    """Result of confidence-weighted plate voting (Eq. 4)."""

    plate_number: str
    agreement_fraction: float
    total_confidence: float
    frames_voted: int
    is_final: bool


class PlateVoter:
    """Collects normalized plate reads across frames per track_id and votes via Eq. 4.

    Eq. 4:
      S* = argmax_{s} sum_{i in frames with s_i = s} c_i
    """

    def __init__(
        self,
        track_id: int,
        min_frames: Optional[int] = None,
        max_frames: Optional[int] = None,
    ):
        self.track_id = track_id
        self.min_frames = (
            min_frames if min_frames is not None else settings.ocr_vote_min_frames
        )
        self.max_frames = (
            max_frames if max_frames is not None else settings.ocr_vote_max_frames
        )
        self.reads: List[Tuple[str, float]] = []

    def add_read(
        self,
        text: Optional[str],
        confidence: float,
    ) -> Optional[VoteResult]:
        """Add a candidate read. If max_frames reached, auto-finalizes and returns VoteResult."""
        if text:
            normalized = normalize_plate(text)
            if normalized:
                self.reads.append((normalized, float(confidence)))
                if len(self.reads) >= self.max_frames:
                    return self.finalize()
        return None

    def can_finalize(self) -> bool:
        """Returns True if at least min_frames (5) valid reads have been gathered."""
        return len(self.reads) >= self.min_frames

    def finalize(self) -> Optional[VoteResult]:
        """Compute winning plate string S* via Eq. 4 (argmax sum of confidences)."""
        if len(self.reads) < self.min_frames:
            return None

        # Equation 4: Sum of confidences for each distinct candidate string
        conf_sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}

        for text, conf in self.reads:
            conf_sums[text] = conf_sums.get(text, 0.0) + conf
            counts[text] = counts.get(text, 0) + 1

        # S* = argmax over strings of sum of confidences
        best_plate = max(conf_sums.keys(), key=lambda s: (conf_sums[s], counts[s]))
        best_conf = conf_sums[best_plate]
        agreement_count = counts[best_plate]
        agreement_fraction = agreement_count / len(self.reads)

        return VoteResult(
            plate_number=best_plate,
            agreement_fraction=float(agreement_fraction),
            total_confidence=float(best_conf),
            frames_voted=len(self.reads),
            is_final=True,
        )
