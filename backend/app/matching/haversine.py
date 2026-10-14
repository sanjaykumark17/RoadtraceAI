"""Haversine distance and kinematic speed estimation utilities (Eq. 6 & 7)."""

from datetime import datetime
import math
from typing import Optional

from app.core.config import settings


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    radius_km: Optional[float] = None,
) -> float:
    """Calculate the great-circle distance between two points on Earth in kilometers (Eq. 6).

    Args:
        lat1: Latitude of point 1 in degrees.
        lon1: Longitude of point 1 in degrees.
        lat2: Latitude of point 2 in degrees.
        lon2: Longitude of point 2 in degrees.
        radius_km: Mean radius of Earth in km (default from settings.earth_radius_km = 6371.0).

    Returns:
        Great-circle distance in kilometers.
    """
    r = radius_km if radius_km is not None else settings.earth_radius_km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    # Numerical clamp to valid range [0.0, 1.0]
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def est_speed_kmh(
    lat1: float,
    lon1: float,
    t1: datetime,
    lat2: float,
    lon2: float,
    t2: datetime,
    radius_km: Optional[float] = None,
) -> float:
    """Estimate kinematic speed between two spatio-temporal sightings in km/h (Eq. 7).

    Guards against delta_t <= 0 and enforces a minimum delta_t of 1 second
    to prevent division blow-ups.

    Args:
        lat1: Latitude of sighting 1 in degrees.
        lon1: Longitude of sighting 1 in degrees.
        t1: Timestamp of sighting 1 (UTC).
        lat2: Latitude of sighting 2 in degrees.
        lon2: Longitude of sighting 2 in degrees.
        t2: Timestamp of sighting 2 (UTC).
        radius_km: Mean radius of Earth in km (default 6371.0).

    Returns:
        Estimated speed in km/h.
    """
    distance_km = haversine_km(lat1, lon1, lat2, lon2, radius_km=radius_km)

    # Calculate absolute time difference in seconds
    delta_seconds = abs((t2 - t1).total_seconds())

    # Guard delta_t <= 0 and enforce minimum of 1.0 second
    delta_seconds = max(delta_seconds, 1.0)

    delta_hours = delta_seconds / 3600.0
    return float(distance_km / delta_hours)


def road_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    radius_km: Optional[float] = None,
    osrm_url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> float:
    """Calculate road distance in kilometers using OSRM /table/ endpoint with Haversine fallback.

    If lat1 == lat2 and lon1 == lon2, returns 0.0 immediately.
    If OSRM is reachable and returns a valid distance, returns road distance in km.
    If OSRM is unreachable, times out, or returns an error, falls back to haversine_km.
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    from app.matching.road_distance import query_osrm_table_distance

    dist = query_osrm_table_distance(
        lat1, lon1, lat2, lon2, osrm_url=osrm_url, timeout=timeout
    )
    if dist is not None:
        return dist

    return haversine_km(lat1, lon1, lat2, lon2, radius_km=radius_km)
