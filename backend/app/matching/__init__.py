"""Matching package exports."""

from app.matching.haversine import est_speed_kmh, haversine_km, road_distance_km
from app.matching.matcher import MatchResult, get_vehicle_last_sighting, match
from app.matching.road_distance import (
    async_get_snapped_segment,
    async_query_osrm_route,
    async_query_osrm_table_distance,
    get_snapped_segment,
    query_osrm_route,
    query_osrm_table_distance,
)

__all__ = [
    "haversine_km",
    "road_distance_km",
    "est_speed_kmh",
    "MatchResult",
    "get_vehicle_last_sighting",
    "match",
    "query_osrm_route",
    "async_query_osrm_route",
    "query_osrm_table_distance",
    "async_query_osrm_table_distance",
    "get_snapped_segment",
    "async_get_snapped_segment",
]
