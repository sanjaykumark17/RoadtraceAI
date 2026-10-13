from typing import Any, Dict, List, Optional

import numpy as np
from ultralytics import YOLO

from app.core.config import settings
from app.models.enums import VehicleClass

# COCO 80-class mapping to RoadTrace AI 4 vehicle classes:
# 2: car -> passenger_car
# 3: motorcycle -> two_wheeler
# 5: bus -> public_bus
# 7: truck -> commercial_truck
COCO_TO_VEHICLE_CLASS: Dict[int, VehicleClass] = {
    2: VehicleClass.passenger_car,
    3: VehicleClass.two_wheeler,
    5: VehicleClass.public_bus,
    7: VehicleClass.commercial_truck,
}

VEHICLE_CLASS_IDS: List[int] = list(COCO_TO_VEHICLE_CLASS.keys())


class YOLODetector:
    """Singleton YOLOv8m detector loading weights once per worker process."""

    _instance: Optional["YOLODetector"] = None
    _model: Optional[YOLO] = None

    def __new__(cls, *args, **kwargs) -> "YOLODetector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, weights: Optional[str] = None):
        if YOLODetector._model is None:
            weights_path = weights or getattr(settings, "yolo_weights", "yolov8m.pt")
            YOLODetector._model = YOLO(weights_path)
        self.model = YOLODetector._model

    @classmethod
    def set_model(cls, model: YOLO) -> None:
        """Allow injecting a model instance (e.g. for testing or mocking)."""
        cls._model = model
        if cls._instance is not None:
            cls._instance.model = model

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (e.g. for testing)."""
        cls._instance = None
        cls._model = None

    def detect_raw(
        self,
        frame: np.ndarray,
        conf: float = 0.1,
        iou: Optional[float] = None,
    ) -> Any:
        """Run YOLO inference returning raw Ultralytics Results object.

        Uses conf=0.1 by default so low-confidence detections are available
        for ByteTrack's second association pass.
        """
        if iou is None:
            iou = settings.nms_iou

        results = self.model(
            frame,
            classes=VEHICLE_CLASS_IDS,
            conf=conf,
            iou=iou,
            verbose=False,
        )
        return results[0]

    def detect_vehicles(
        self,
        frame: np.ndarray,
        conf: Optional[float] = None,
        iou: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Detect vehicles filtered by confidence threshold (conf >= 0.45).

        Returns:
            List of dicts: {
                "bbox_xyxy": (x1, y1, x2, y2),
                "conf": float,
                "vehicle_class": VehicleClass,
                "class_id": int
            }
        """
        if conf is None:
            conf = settings.vehicle_conf
        if iou is None:
            iou = settings.nms_iou

        result = self.detect_raw(frame, conf=conf, iou=iou)
        detections: List[Dict[str, Any]] = []

        if result.boxes is not None and len(result.boxes) > 0:
            boxes_data = result.boxes.cpu().numpy()
            for box in boxes_data:
                score = float(box.conf[0])
                if score < conf:
                    continue
                cls_id = int(box.cls[0])
                v_class = COCO_TO_VEHICLE_CLASS.get(cls_id)
                if v_class is None:
                    continue

                xyxy = tuple(float(x) for x in box.xyxy[0])
                detections.append(
                    {
                        "bbox_xyxy": xyxy,
                        "conf": score,
                        "vehicle_class": v_class,
                        "class_id": cls_id,
                    }
                )

        return detections


def get_detector(weights: Optional[str] = None) -> YOLODetector:
    """Convenience getter for singleton YOLO detector."""
    return YOLODetector(weights=weights)
