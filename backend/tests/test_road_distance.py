"""Unit tests for OSRM road distance, route snapping, and fallback behavior."""

from unittest.mock import MagicMock, patch

import pytest
from app.matching.haversine import haversine_km, road_distance_km
from app.matching.road_distance import (
    async_get_snapped_segment,
    get_snapped_segment,
    query_osrm_route,
    query_osrm_table_distance,
)


def test_road_distance_identical_points():
    """Identical points must return 0.0 distance immediately without network call."""
    assert road_distance_km(13.0827, 80.2707, 13.0827, 80.2707) == 0.0
    assert query_osrm_table_distance(13.0827, 80.2707, 13.0827, 80.2707) == 0.0


def test_road_distance_fallback_when_osrm_unreachable():
    """When OSRM is unreachable, road_distance_km must gracefully fall back to Haversine."""
    lat1, lon1 = 13.0827, 80.2707
    lat2, lon2 = 12.9866, 80.1707

    # Point to non-existent port
    dist = road_distance_km(
        lat1,
        lon1,
        lat2,
        lon2,
        osrm_url="http://127.0.0.1:54321",
        timeout=0.2,
    )
    expected_haversine = haversine_km(lat1, lon1, lat2, lon2)
    assert dist == pytest.approx(expected_haversine, rel=1e-3)


def test_get_snapped_segment_fallback_when_osrm_unreachable():
    """When OSRM route is unreachable, return straight-line coordinates."""
    p1 = [80.2707, 13.0827]
    p2 = [80.1707, 12.9866]

    coords = get_snapped_segment(
        p1,
        p2,
        osrm_url="http://127.0.0.1:54321",
        timeout=0.2,
    )
    assert coords == [p1, p2]


@pytest.mark.asyncio
async def test_async_get_snapped_segment_fallback():
    """Async snapped segment fallback returns straight line on connection failure."""
    p1 = [80.1, 13.0]
    p2 = [80.2, 13.1]
    coords = await async_get_snapped_segment(
        p1,
        p2,
        osrm_url="http://127.0.0.1:54321",
        timeout=0.2,
    )
    assert coords == [p1, p2]


def test_road_distance_with_mocked_osrm_table():
    """When OSRM responds with valid distance, return road distance in km."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": "Ok",
        "distances": [[0.0, 18450.0], [18450.0, 0.0]],
    }

    with patch("httpx.Client.get", return_value=mock_response):
        dist = road_distance_km(13.0827, 80.2707, 12.9866, 80.1707)
        assert dist == 18.45


def test_route_snapping_with_mocked_osrm_route():
    """When OSRM route endpoint responds, return the snapped coordinates."""
    mock_coords = [
        [80.1491, 12.9675],
        [80.1520, 12.9710],
        [80.1580, 12.9740],
        [80.1600, 12.9750],
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": "Ok",
        "routes": [
            {
                "geometry": {"coordinates": mock_coords, "type": "LineString"},
                "distance": 2400.0,
                "duration": 180.0,
            }
        ],
    }

    with patch("httpx.Client.get", return_value=mock_response):
        result = query_osrm_route([[80.1491, 12.9675], [80.1600, 12.9750]])
        assert result is not None
        assert result["coordinates"] == mock_coords
        assert result["distance_meters"] == 2400.0
