"""Matching service stub (to be fully implemented in Step 9)."""
import logging
from typing import Any, Optional

from app.models.sighting import Sighting

logger = logging.getLogger("roadtrace.matching")


class MatchingService:
    """Stub matching service for spatio-temporal route and candidate matching."""

    async def ingest_sighting(
        self, sighting: Sighting, db: Optional[Any] = None
    ) -> dict[str, Any]:
        """Ingest a newly detected plate sighting into the matching engine."""
        logger.info(
            "matching_service: ingested sighting id=%s plate=%s cam=%s conf=%.3f",
            getattr(sighting, "id", None),
            getattr(sighting, "plate_number", ""),
            getattr(sighting, "camera_id", None),
            getattr(sighting, "ocr_confidence", 0.0),
        )
        return {
            "status": "ingested",
            "sighting_id": getattr(sighting, "id", None),
            "plate_number": getattr(sighting, "plate_number", ""),
        }


matching_service = MatchingService()
