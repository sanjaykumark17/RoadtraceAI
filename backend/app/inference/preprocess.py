from typing import Optional, Tuple, Union

import cv2
import numpy as np

from app.core.config import settings


def letterbox(
    frame: np.ndarray,
    target_size: Optional[int] = None,
    color: Tuple[int, int, int] = (114, 114, 114),
) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """Resize and pad image to target_size x target_size preserving aspect ratio.

    Returns:
        letterboxed: Exactly target_size x target_size image.
        scale: Scale factor applied to original image.
        pad_offsets: (pad_left, pad_top) in pixels.
    """
    if target_size is None:
        target_size = settings.input_size

    orig_h, orig_w = frame.shape[:2]
    scale = min(target_size / orig_h, target_size / orig_w)
    new_w = int(round(orig_w * scale))
    new_h = int(round(orig_h * scale))

    pad_w = target_size - new_w
    pad_h = target_size - new_h
    pad_left = pad_w // 2
    pad_top = pad_h // 2
    pad_right = pad_w - pad_left
    pad_bottom = pad_h - pad_top

    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    letterboxed = cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=color,
    )
    return letterboxed, scale, (pad_left, pad_top)


def unletterbox_box(
    box: Union[Tuple[float, float, float, float], np.ndarray, list],
    scale: float,
    pad_offsets: Tuple[int, int],
    orig_shape: Optional[Tuple[int, int]] = None,
) -> Tuple[float, float, float, float]:
    """Map a bounding box (x1, y1, x2, y2) from letterboxed space back to original space."""
    pad_x, pad_y = pad_offsets
    x1 = (box[0] - pad_x) / scale
    y1 = (box[1] - pad_y) / scale
    x2 = (box[2] - pad_x) / scale
    y2 = (box[3] - pad_y) / scale

    if orig_shape is not None:
        orig_h, orig_w = orig_shape[:2]
        x1 = max(0.0, min(float(x1), float(orig_w)))
        y1 = max(0.0, min(float(y1), float(orig_h)))
        x2 = max(0.0, min(float(x2), float(orig_w)))
        y2 = max(0.0, min(float(y2), float(orig_h)))

    return float(x1), float(y1), float(x2), float(y2)


def unletterbox_boxes(
    boxes: np.ndarray,
    scale: float,
    pad_offsets: Tuple[int, int],
    orig_shape: Optional[Tuple[int, int]] = None,
) -> np.ndarray:
    """Map an array of bounding boxes (N, 4) from letterboxed space back to original space."""
    if len(boxes) == 0:
        return boxes.copy()

    pad_x, pad_y = pad_offsets
    res = boxes.astype(np.float32).copy()
    res[:, 0] = (res[:, 0] - pad_x) / scale
    res[:, 1] = (res[:, 1] - pad_y) / scale
    res[:, 2] = (res[:, 2] - pad_x) / scale
    res[:, 3] = (res[:, 3] - pad_y) / scale

    if orig_shape is not None:
        orig_h, orig_w = orig_shape[:2]
        res[:, 0] = np.clip(res[:, 0], 0, orig_w)
        res[:, 1] = np.clip(res[:, 1], 0, orig_h)
        res[:, 2] = np.clip(res[:, 2], 0, orig_w)
        res[:, 3] = np.clip(res[:, 3], 0, orig_h)

    return res


def blur_score(crop: np.ndarray) -> float:
    """Calculate blur metric: variance of cv2.Laplacian(gray, CV_64F)."""
    if crop.size == 0:
        return 0.0

    if crop.ndim == 3:
        if crop.shape[2] == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        elif crop.shape[2] == 4:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
        else:
            gray = crop[:, :, 0]
    else:
        gray = crop

    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return float(laplacian.var())


def is_blurry(crop: np.ndarray, tau: Optional[float] = None) -> bool:
    """Return True if crop blur score is strictly below threshold tau."""
    if tau is None:
        tau = float(settings.blur_tau)
    return blur_score(crop) < tau


def enhance_plate(crop: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Enhance number plate crop for OCR.

    Pipeline:
      1. Grayscale
      2. CLAHE (clipLimit=2.0, tileGridSize=(8, 8))
      3. Bilateral filter (d=9, sigmaColor=75, sigmaSpace=75)
      4. Otsu binarization

    Returns:
        (enhanced_gray, binary_image)
    """
    if crop.ndim == 3:
        if crop.shape[2] == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        elif crop.shape[2] == 4:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
        else:
            gray = crop[:, :, 0]
    else:
        gray = crop.copy()

    # 2. CLAHE
    clahe = cv2.createCLAHE(
        clipLimit=settings.clahe_clip_limit,
        tileGridSize=settings.clahe_tile_grid,
    )
    clahe_img = clahe.apply(gray)

    # 3. Bilateral Filter
    filtered = cv2.bilateralFilter(
        clahe_img,
        d=settings.bilateral_d,
        sigmaColor=settings.bilateral_sigma_color,
        sigmaSpace=settings.bilateral_sigma_space,
    )

    # 4. Otsu binarization
    _, binary = cv2.threshold(
        filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    return filtered, binary
