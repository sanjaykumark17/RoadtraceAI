"""Lazy-loading inference module to avoid importing torch/ultralytics eagerly."""

import importlib
from typing import Any

_EXPORTS = {
    # ingest
    "FrameSource": "app.inference.ingest",
    # preprocess
    "blur_score": "app.inference.preprocess",
    "enhance_plate": "app.inference.preprocess",
    "is_blurry": "app.inference.preprocess",
    "letterbox": "app.inference.preprocess",
    "unletterbox_box": "app.inference.preprocess",
    "unletterbox_boxes": "app.inference.preprocess",
    # detector
    "COCO_TO_VEHICLE_CLASS": "app.inference.detector",
    "VEHICLE_CLASS_IDS": "app.inference.detector",
    "YOLODetector": "app.inference.detector",
    "get_detector": "app.inference.detector",
    # tracker
    "TrackedVehicle": "app.inference.tracker",
    "VehicleTracker": "app.inference.tracker",
    "get_tracker": "app.inference.tracker",
    "reset_trackers": "app.inference.tracker",
    # plate_ocr
    "DIGIT_TO_LETTER": "app.inference.plate_ocr",
    "LETTER_TO_DIGIT": "app.inference.plate_ocr",
    "OCR_ALLOWLIST": "app.inference.plate_ocr",
    "OCRReaderSingleton": "app.inference.plate_ocr",
    "PlateDetectorSingleton": "app.inference.plate_ocr",
    "PlateVoter": "app.inference.plate_ocr",
    "VoteResult": "app.inference.plate_ocr",
    "normalize_plate": "app.inference.plate_ocr",
    "process_vehicle_crop_for_plate": "app.inference.plate_ocr",
    "read_plate_text": "app.inference.plate_ocr",
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        mod = importlib.import_module(_EXPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
