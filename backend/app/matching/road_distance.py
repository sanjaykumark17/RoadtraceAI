"""OSRM road-snapping and distance calculation helpers.

Supports OSRM /route/v1/driving/ and /table/v1/driving/ with graceful fallback
to straight lines and haversine calculations when OSRM is unreachable.
"""

from typing import Any
import httpx

from app.core.config import settings


def query_osrm_table_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    osrm_url: str | None = None,
    timeout: float | None = None,
) -> float | None:
    """Query OSRM /table/v1/driving/ for road distance in kilometers.

    Returns distance in km, or None if OSRM is unreachable or errors out.
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    base_url = (osrm_url or settings.osrm_url).rstrip("/")
    t = timeout if timeout is not None else settings.osrm_timeout
    url = f"{base_url}/table/v1/driving/{lon1},{lat1};{lon2},{lat2}?annotations=distance"

    try:
        with httpx.Client(timeout=t) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "Ok" and "distances" in data:
                    meters = data["distances"][0][1]
                    if meters is not None:
                        return float(meters) / 1000.0
    except Exception:
        # Fallback to None if OSRM is unreachable / times out
        return None

    return None


async def async_query_osrm_table_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    osrm_url: str | None = None,
    timeout: float | None = None,
) -> float | None:
    """Async version of query_osrm_table_distance."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    base_url = (osrm_url or settings.osrm_url).rstrip("/")
    t = timeout if timeout is not None else settings.osrm_timeout
    url = f"{base_url}/table/v1/driving/{lon1},{lat1};{lon2},{lat2}?annotations=distance"

    try:
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "Ok" and "distances" in data:
                    meters = data["distances"][0][1]
                    if meters is not None:
                        return float(meters) / 1000.0
    except Exception:
        return None

    return None


def query_osrm_route(
    coordinates: list[list[float]] | list[tuple[float, float]],
    osrm_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    """Query OSRM /route/v1/driving/ for road-snapped geometry.

    Args:
        coordinates: List of [lon, lat] or (lon, lat) points in GeoJSON order.
        osrm_url: OSRM service base URL.
        timeout: Request timeout in seconds.

    Returns:
        Dict with "coordinates" (list of [lon, lat]), "distance_meters", "duration_seconds",
        or None if OSRM is unreachable or request fails.
    """
    if not coordinates or len(coordinates) < 2:
        return None

    base_url = (osrm_url or settings.osrm_url).rstrip("/")
    t = timeout if timeout is not None else settings.osrm_timeout
    coord_str = ";".join(f"{c[0]},{c[1]}" for c in coordinates)
    url = f"{base_url}/route/v1/driving/{coord_str}?overview=full&geometries=geojson"

    try:
        with httpx.Client(timeout=t) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    route = data["routes"][0]
                    return {
                        "coordinates": route["geometry"]["coordinates"],
                        "distance_meters": route.get("distance", 0.0),
                        "duration_seconds": route.get("duration", 0.0),
                    }
    except Exception:
        return None

    return None


async def async_query_osrm_route(
    coordinates: list[list[float]] | list[tuple[float, float]],
    osrm_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Async query OSRM /route/v1/driving/ for road-snapped route geometry."""
    if not coordinates or len(coordinates) < 2:
        return None

    base_url = (osrm_url or settings.osrm_url).rstrip("/")
    t = timeout if timeout is not None else settings.osrm_timeout
    coord_str = ";".join(f"{c[0]},{c[1]}" for c in coordinates)
    url = f"{base_url}/route/v1/driving/{coord_str}?overview=full&geometries=geojson"

    try:
        if client is not None:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "Ok" and data.get("routes"):
                    route = data["routes"][0]
                    return {
                        "coordinates": route["geometry"]["coordinates"],
                        "distance_meters": route.get("distance", 0.0),
                        "duration_seconds": route.get("duration", 0.0),
                    }
        else:
            async with httpx.AsyncClient(timeout=t) as ac:
                resp = await ac.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "Ok" and data.get("routes"):
                        route = data["routes"][0]
                        return {
                            "coordinates": route["geometry"]["coordinates"],
                            "distance_meters": route.get("distance", 0.0),
                            "duration_seconds": route.get("duration", 0.0),
                        }
    except Exception:
        return None

    return None


def get_snapped_segment(
    p1: list[float] | tuple[float, float],
    p2: list[float] | tuple[float, float],
    osrm_url: str | None = None,
    timeout: float | None = None,
) -> list[list[float]]:
    """Return road-snapped [lon, lat] coordinates between two points.

    Falls back to straight-line [[p1_lon, p1_lat], [p2_lon, p2_lat]] if OSRM is unreachable.
    """
    p1_coords = [float(p1[0]), float(p1[1])]
    p2_coords = [float(p2[0]), float(p2[1])]

    result = query_osrm_route([p1_coords, p2_coords], osrm_url=osrm_url, timeout=timeout)
    if result and result.get("coordinates"):
        return result["coordinates"]

    return [p1_coords, p2_coords]


async def async_get_snapped_segment(
    p1: list[float] | tuple[float, float],
    p2: list[float] | tuple[float, float],
    osrm_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    """Async return road-snapped [lon, lat] coordinates between two points with straight-line fallback."""
    p1_coords = [float(p1[0]), float(p1[1])]
    p2_coords = [float(p2[0]), float(p2[1])]

    result = await async_query_osrm_route(
        [p1_coords, p2_coords],
        osrm_url=osrm_url,
        timeout=timeout,
        client=client,
    )
    if result and result.get("coordinates"):
        return result["coordinates"]

    return [p1_coords, p2_coords]
