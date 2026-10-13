import re

from app.core.config import settings


def test_input_size():
    assert settings.input_size == 640


def test_vehicle_conf():
    assert settings.vehicle_conf == 0.45


def test_nms_iou():
    assert settings.nms_iou == 0.50


def test_blur_tau():
    assert settings.blur_tau == 100


def test_clahe_clip_limit():
    assert settings.clahe_clip_limit == 2.0


def test_clahe_tile_grid():
    assert settings.clahe_tile_grid == (8, 8)


def test_plate_regex_valid():
    pattern = re.compile(settings.plate_regex)
    assert pattern.match("MH12AB1234")
    assert pattern.match("KA01A0001")


def test_plate_regex_invalid():
    pattern = re.compile(settings.plate_regex)
    assert not pattern.match("1234AB")
    assert not pattern.match("MH12AB12345")


def test_ocr_vote_window():
    assert settings.ocr_vote_min_frames == 5
    assert settings.ocr_vote_max_frames == 15


def test_levenshtein_max():
    assert settings.levenshtein_max == 2


def test_v_max_kmh():
    assert settings.v_max_kmh == 150.0


def test_earth_radius_km():
    assert settings.earth_radius_km == 6371.0


def test_access_token_expire():
    assert settings.access_token_expire_minutes == 15


def test_refresh_token_expire():
    assert settings.refresh_token_expire_days == 7


def test_roles():
    assert settings.roles == ["admin", "operator", "viewer"]


def test_algorithm():
    assert settings.algorithm == "HS256"
