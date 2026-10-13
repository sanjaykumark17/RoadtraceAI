"""WebSocket endpoints for real-time trajectory and sighting streaming."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.session import AsyncSession
from app.services.audit import write_audit_log
from app.services.notifier import broadcaster

logger = logging.getLogger("roadtrace.websocket")

router = APIRouter(tags=["websockets"])


def format_sighting_message(data: dict[str, Any]) -> dict[str, Any]:
    """Format sighting notification into GeoJSON Point feature and payload."""
    lat = float(data.get("latitude", 0.0) or 0.0)
    lon = float(data.get("longitude", 0.0) or 0.0)
    cam_name = data.get("camera_name", "")
    snap_path = data.get("snapshot_path")
    snap_url = data.get("snapshot_url")
    if not snap_url and snap_path:
        snap_url = f"/snapshots/{Path(snap_path).name}"

    plate = data.get("plate_number", "")

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": {
            "camera_name": cam_name,
            "camera": cam_name,
            "latitude": lat,
            "longitude": lon,
            "timestamp": data.get("timestamp"),
            "plate": plate,
            "plate_number": plate,
            "ocr_confidence": data.get("ocr_confidence"),
            "snapshot_url": snap_url,
        },
        "sighting": data,
        "plate": plate,
        "plate_number": plate,
        "timestamp": data.get("timestamp"),
        "camera_name": cam_name,
        "latitude": lat,
        "longitude": lon,
    }


@router.websocket("/ws/trajectory/{plate}")
async def ws_trajectory_feed(websocket: WebSocket, plate: str):
    """Stream newly recorded sightings for vehicle plate in near real time via Postgres LISTEN/NOTIFY."""
    await websocket.accept()

    # Log websocket connection to audit_logs
    try:
        async with AsyncSession() as session:
            await write_audit_log(
                session,
                user_id=None,
                action="trace",
                resource="vehicles",
                resource_id=plate,
                ip=websocket.client.host if websocket.client else None,
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to record audit log for websocket: {e}")

    queue = await broadcaster.subscribe(plate)

    async def receive_client_messages():
        try:
            while True:
                # Keep read open for client pings or close frames
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    client_task = asyncio.create_task(receive_client_messages())

    try:
        while True:
            # Wait for either new sighting from queue or client disconnect
            queue_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                [queue_task, client_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if client_task in done:
                for p in pending:
                    p.cancel()
                break

            if queue_task in done:
                sighting_data = queue_task.result()
                msg = format_sighting_message(sighting_data)
                await websocket.send_json(msg)
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from trajectory websocket for {plate}")
    except Exception as e:
        logger.warning(f"Websocket error for {plate}: {e}")
    finally:
        client_task.cancel()
        await broadcaster.unsubscribe(plate, queue)
