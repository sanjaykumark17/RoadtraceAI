"""Matching service orchestrating the 3-tier matcher."""

import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.db.session import AsyncSession
from app.matching.matcher import MatchResult, match
from app.models.sighting import Sighting

logger = logging.getLogger("roadtrace.matching")


class MatchingService:
    """Service orchestrating spatio-temporal vehicle matching and alert triggers."""

    async def ingest_sighting(
        self,
        sighting: Sighting,
        db: Optional[SAAsyncSession] = None,
    ) -> Dict[str, Any]:
        """Ingest and match a newly created plate sighting.

        Coordinates exact, fuzzy-kinematic, or new-vehicle matching
        and active alert evaluation in a single atomic database transaction.
        """
        if db is not None:
            result: MatchResult = await match(sighting, db)
        else:
            async with AsyncSession() as session:
                result = await match(sighting, session)

        logger.info(
            f"MatchingService: ingested sighting {sighting.id} plate {sighting.plate_number} "
            f"matched to vehicle {result.vehicle.id} ({result.vehicle.plate_number}) "
            f"tier={result.tier} triggers={result.triggers_created}"
        )

        return {
            "status": "ingested",
            "tier": result.tier,
            "vehicle_id": result.vehicle.id,
            "plate_number": result.vehicle.plate_number,
            "speed_kmh": result.speed_kmh,
            "flag": result.flag,
            "triggers_created": result.triggers_created,
            "sighting_id": sighting.id,
        }


matching_service = MatchingService()
