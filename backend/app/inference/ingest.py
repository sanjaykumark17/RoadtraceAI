from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import Generator, Optional, Tuple, Union

import cv2
import numpy as np


class FrameSource:
    """Reads video frames from an MP4 file or RTSP stream with OpenCV.

    Yields (frame, frame_index, utc_timestamp).
    - For files: utc_timestamp = start_time + timedelta(seconds=frame_index / fps).
    - For RTSP streams: utc_timestamp = datetime.now(timezone.utc) (wall-clock UTC).
    - Supports processing every Nth frame via `step` parameter.
    - Supports automatic RTSP reconnect with configurable retries.
    """

    def __init__(
        self,
        source: Union[str, Path],
        start_time: Optional[datetime] = None,
        step: int = 1,
        default_fps: float = 25.0,
        is_rtsp: Optional[bool] = None,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
    ):
        self.source = str(source)
        self.start_time = start_time or datetime.now(timezone.utc)
        self.step = max(1, int(step))
        self.default_fps = float(default_fps)
        self.max_reconnect_attempts = int(max_reconnect_attempts)
        self.reconnect_delay = float(reconnect_delay)

        if is_rtsp is not None:
            self.is_rtsp = bool(is_rtsp)
        else:
            s_lower = self.source.lower()
            self.is_rtsp = s_lower.startswith("rtsp://") or s_lower.startswith("rtsps://")

        self._cap: Optional[cv2.VideoCapture] = None

    def _open_capture(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(self.source)

    def _reconnect(self) -> bool:
        """Attempt to reconnect to RTSP stream."""
        for _ in range(1, self.max_reconnect_attempts + 1):
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
            if self.reconnect_delay > 0:
                time.sleep(self.reconnect_delay)
            try:
                cap = self._open_capture()
                if cap.isOpened():
                    self._cap = cap
                    return True
            except Exception:
                pass
        return False

    def close(self) -> None:
        """Release underlying video capture resource."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __iter__(self) -> Generator[Tuple[np.ndarray, int, datetime], None, None]:
        self._cap = self._open_capture()
        if not self._cap.isOpened() and self.is_rtsp:
            if not self._reconnect():
                return
        elif not self._cap.isOpened():
            return

        try:
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            if not fps or fps <= 0 or np.isnan(fps):
                fps = self.default_fps

            raw_frame_index = 0
            while True:
                if raw_frame_index % self.step == 0:
                    ret, frame = self._cap.read()
                    if not ret:
                        if self.is_rtsp and self._reconnect():
                            continue
                        break

                    if self.is_rtsp:
                        ts = datetime.now(timezone.utc)
                    else:
                        ts = self.start_time + timedelta(
                            seconds=raw_frame_index / fps
                        )

                    yield frame, raw_frame_index, ts
                    raw_frame_index += 1
                else:
                    ret = self._cap.grab()
                    if not ret:
                        if self.is_rtsp and self._reconnect():
                            continue
                        break
                    raw_frame_index += 1
        finally:
            self.close()
