from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
import torch
from ultralytics.engine.results import Boxes

from app.core.config import settings
from app.inference.plate_ocr import (
    DIGIT_TO_LETTER,
    LETTER_TO_DIGIT,
    OCR_ALLOWLIST,
    PlateVoter,
    VoteResult,
    normalize_plate,
    process_vehicle_crop_for_plate,
)
from app.inference.preprocess import is_blurry


def test_normalize_plate_examples_from_spec():
    # Specific test examples from specification:
    # "MHO1AB1234" -> "MH01AB1234"
    assert normalize_plate("MHO1AB1234") == "MH01AB1234"

    # "TN1OAB1234" -> "TN10AB1234"
    assert normalize_plate("TN1OAB1234") == "TN10AB1234"


def test_normalize_plate_positional_confusion_mapping():
    # Format AA 00 AA 0000 (length 10)
    # Digits in letter positions: 0->O, 1->I, 8->B, 5->S, 2->Z, 6->G
    assert normalize_plate("0H01AB1234") == "OH01AB1234"  # 0 -> O
    assert normalize_plate("MH018B1234") == "MH01BB1234"  # 8 -> B
    assert normalize_plate("MH015B1234") == "MH01SB1234"  # 5 -> S
    assert normalize_plate("MH012B1234") == "MH01ZB1234"  # 2 -> Z
    assert normalize_plate("MH016B1234") == "MH01GB1234"  # 6 -> G
    assert normalize_plate("1H01AB1234") == "IH01AB1234"  # 1 -> I

    # Letters in digit positions: O->0, I->1, B->8, S->5, Z->2, G->6, D->0
    assert normalize_plate("MH01AB123I") == "MH01AB1231"  # I -> 1
    assert normalize_plate("MH01AB123B") == "MH01AB1238"  # B -> 8
    assert normalize_plate("MH01AB123S") == "MH01AB1235"  # S -> 5
    assert normalize_plate("MH01AB123Z") == "MH01AB1232"  # Z -> 2
    assert normalize_plate("MH01AB123G") == "MH01AB1236"  # G -> 6
    assert normalize_plate("MH01AB123D") == "MH01AB1230"  # D -> 0
    assert normalize_plate("MHOIAB1234") == "MH01AB1234"  # O->0, I->1


def test_normalize_plate_9_character_plates():
    # Format AA 00 A 0000 (1 series letter)
    assert normalize_plate("KA01A0001") == "KA01A0001"
    assert normalize_plate("KAO1AOOO1") == "KA01A0001"  # O in digit positions -> 0
    assert normalize_plate("KA0110001") == "KA01I0001"  # 1 in series letter position -> I


def test_normalize_plate_regex_rejection():
    # Invalid lengths or formats must return None
    assert normalize_plate("1234AB") is None
    assert normalize_plate("MH12AB12345") is None  # 11 chars
    assert normalize_plate("INVALID123") is None
    assert normalize_plate("3333333333") is None  # Digits '3' cannot map to letters at pos 0, 1
    assert normalize_plate("AAAA999999") is None  # Letters 'A' cannot map to digits at pos 2, 3
    assert normalize_plate("") is None
    assert normalize_plate("MH-01-$$$") is None


def test_plate_voter_equation_4_confidence_weighted_majority():
    # Equation 4: S* = argmax_{s} sum_{i in frames with s_i = s} c_i
    # Test case:
    # Candidate A ("MH01AB1234") has 3 frames with high confidence (0.95 each -> sum = 2.85)
    # Candidate B ("MH01AB1235") has 4 frames with lower confidence (0.50 each -> sum = 2.00)
    # Simple vote count would pick Candidate B (4 vs 3).
    # Confidence-weighted Eq. 4 MUST pick Candidate A (2.85 vs 2.00)!
    voter = PlateVoter(track_id=1, min_frames=5, max_frames=15)

    # 3 high-confidence reads for Candidate A
    for _ in range(3):
        voter.add_read("MH01AB1234", confidence=0.95)

    # 4 lower-confidence reads for Candidate B
    for _ in range(4):
        voter.add_read("MH01AB1235", confidence=0.50)

    # Total reads = 7 (>= min_frames=5)
    assert voter.can_finalize() is True
    result = voter.finalize()

    assert result is not None
    assert result.plate_number == "MH01AB1234", (
        f"Eq. 4 should pick Candidate A with sum 2.85 over Candidate B with sum 2.00, got {result.plate_number}"
    )
    assert result.total_confidence == pytest.approx(2.85, abs=1e-3)
    assert result.agreement_fraction == pytest.approx(3 / 7, abs=1e-3)
    assert result.frames_voted == 7


def test_plate_voter_thresholds_and_finalization():
    voter = PlateVoter(track_id=42, min_frames=5, max_frames=15)

    # Fewer than 5 reads cannot finalize
    for _ in range(4):
        res = voter.add_read("TN01CD5678", confidence=0.9)
        assert res is None
    assert voter.can_finalize() is False
    assert voter.finalize() is None

    # 5th read allows manual finalization
    voter.add_read("TN01CD5678", confidence=0.9)
    assert voter.can_finalize() is True
    fin = voter.finalize()
    assert fin is not None
    assert fin.plate_number == "TN01CD5678"
    assert fin.frames_voted == 5

    # Auto-finalizes at max_frames = 15
    voter2 = PlateVoter(track_id=43, min_frames=5, max_frames=15)
    auto_res = None
    for i in range(15):
        auto_res = voter2.add_read("KA05EF9012", confidence=0.8)
        if i < 14:
            assert auto_res is None

    # On the 15th read, auto_res is returned directly
    assert auto_res is not None
    assert auto_res.plate_number == "KA05EF9012"
    assert auto_res.frames_voted == 15
    assert auto_res.agreement_fraction == 1.0


def test_process_vehicle_crop_pipeline():
    # 1. Blurry crop is skipped
    blurry_crop = np.full((100, 200, 3), 128, dtype=np.uint8)
    # Uniform color has 0 variance (variance < 100) -> blurry
    assert is_blurry(blurry_crop, tau=100) is True
    res_text, res_conf, _ = process_vehicle_crop_for_plate(
        blurry_crop, blur_threshold=100
    )
    assert res_text is None
    assert res_conf == 0.0

    # 2. Mock plate detector and OCR reader on sharp vehicle crop
    sharp_vehicle = np.zeros((300, 500, 3), dtype=np.uint8)
    # Add high frequency noise so crop is not blurry
    sharp_vehicle[::4, ::4] = 255

    # Mock plate detector returning bounding box with confidence 0.92
    mock_model = MagicMock()
    mock_results = MagicMock()
    mock_results.boxes = Boxes(
        torch.tensor([[150.0, 180.0, 350.0, 240.0, 0.92, 0.0]]),
        orig_shape=(300, 500),
    )
    mock_model.return_value = [mock_results]

    # Mock EasyOCR reader returning raw text with confusion
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([[10, 10], [100, 10], [100, 30], [10, 30]], "MHO1AB1234", 0.94)
    ]

    plate, conf, crop = process_vehicle_crop_for_plate(
        sharp_vehicle,
        plate_detector=mock_model,
        ocr_reader=mock_reader,
        blur_threshold=10,
    )

    # Should be normalized to "MH01AB1234"
    assert plate == "MH01AB1234"
    assert conf == pytest.approx(0.94, abs=1e-2)
    assert crop is not None
    assert crop.shape[0] > 0
    assert crop.shape[1] > 0
