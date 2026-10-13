from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from ultralytics.trackers.byte_tracker import BYTETracker

from app.core.config import settings
from app.inference.detector import COCO_TO_VEHICLE_CLASS, YOLODetector, get_detector
from app.models.enums import VehicleClass


@dataclass
class TrackedVehicle:
    """Represents a tracked vehicle in a specific video frame."""

    track_id: int
    bbox_xyxy: Tuple[float, float, float, float]
    conf: float
    vehicle_class: VehicleClass
    frame_index: int


class VehicleTracker:
    """Maintains a ByteTrack tracker state for a specific camera or job.

    Ensures track IDs and Kalman filter states never mix across cameras.
    """

    def __init__(
        self,
        camera_id: Optional[Union[str, int]] = None,
        job_id: Optional[Union[str, int]] = None,
        tracker_args: Optional[SimpleNamespace] = None,
        output_conf_threshold: Optional[float] = None,
    ):
        self.camera_id = camera_id
        self.job_id = job_id
        self.output_conf_threshold = (
            output_conf_threshold
            if output_conf_threshold is not None
            else settings.vehicle_conf
        )

        # ByteTrack parameters configured to keep low-confidence boxes (track_low_thresh=0.1)
        # for second-stage association pass (helping recover tracks during occlusions)
        self.tracker_args = tracker_args or SimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=0.25,
            track_low_thresh=0.1,
            new_track_thresh=0.25,
            track_buffer=30,
            match_thresh=0.8,
            fuse_score=True,
        )
        self.tracker: BYTETracker = BYTETracker(self.tracker_args)

    def reset(self) -> None:
        """Reset internal tracker state."""
        self.tracker = BYTETracker(self.tracker_args)

    def update(
        self,
        detections: Any,
        frame_index: int,
        img: Optional[np.ndarray] = None,
    ) -> List[TrackedVehicle]:
        """Update tracker with detection boxes and return active tracked vehicles.

        Args:
            detections: Ultralytics Boxes.cpu().numpy() or compatible detection object.
            frame_index: Current frame index in video sequence.
            img: Optional BGR image frame.

        Returns:
            List of TrackedVehicle with conf >= output_conf_threshold (0.45).
        """
        raw_tracks = self.tracker.update(detections, img=img)
        if raw_tracks is None or len(raw_tracks) == 0:
            return []

        tracked_vehicles: List[TrackedVehicle] = []
        for track in raw_tracks:
            x1, y1, x2, y2 = float(track[0]), float(track[1]), float(track[2]), float(track[3])
            track_id = int(track[4])
            score = float(track[5])
            cls_id = int(track[6])

            # Apply output confidence threshold (conf >= 0.45) for OCR eligibility and output
            if score < self.output_conf_threshold:
                continue

            v_class = COCO_TO_VEHICLE_CLASS.get(cls_id, VehicleClass.passenger_car)

            tracked_vehicles.append(
                TrackedVehicle(
                    track_id=track_id,
                    bbox_xyxy=(x1, y1, x2, y2),
                    conf=score,
                    vehicle_class=v_class,
                    frame_index=frame_index,
                )
            )

        return tracked_vehicles

    def track_frame(
        self,
        frame: np.ndarray,
        frame_index: int,
        detector: Optional[YOLODetector] = None,
    ) -> List[TrackedVehicle]:
        """Convenience method to detect and track in a single call."""
        det = detector or get_detector()
        raw_results = det.detect_raw(frame, conf=0.1)
        det_boxes = raw_results.boxes.cpu().numpy()
        return self.update(det_boxes, frame_index=frame_index, img=frame)


# Per-camera/job tracker registry to prevent ID mixing
_tracker_registry: Dict[str, VehicleTracker] = {}


def get_tracker(
    camera_id: Union[str, int],
    job_id: Optional[Union[str, int]] = None,
    reset: bool = False,
) -> VehicleTracker:
    """Retrieve or create a VehicleTracker instance dedicated to a camera/job."""
    key = f"{camera_id}_{job_id}" if job_id is not None else str(camera_id)
    if reset or key not in _tracker_registry:
        _tracker_registry[key] = VehicleTracker(camera_id=camera_id, job_id=job_id)
    return _tracker_registry[key]


def reset_trackers() -> None:
    """Reset all active tracker instances in registry."""
    _tracker_registry.clear()
