from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_db, require_role
from app.models.camera import Camera
from app.models.enums import JobStatus
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.schemas.job import JobCreate, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    content_type = request.headers.get("content-type", "")
    camera_id: Optional[int] = None
    source_uri: str = ""

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid json body",
            )
        camera_id = body.get("camera_id")
        source_uri = body.get("source_uri", "")
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        raw_cam_id = form.get("camera_id")
        if raw_cam_id is not None:
            try:
                camera_id = int(raw_cam_id)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="camera_id must be an integer",
                )
        source_uri = str(form.get("source_uri", "") or "")
        video_file = form.get("video")
        if video_file and hasattr(video_file, "filename") and video_file.filename:
            source_uri = f"upload://{video_file.filename}"
    else:
        # Default try json
        try:
            body = await request.json()
            camera_id = body.get("camera_id")
            source_uri = body.get("source_uri", "")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="unsupported content type or invalid payload",
            )

    try:
        job_data = JobCreate(camera_id=camera_id, source_uri=source_uri)
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err.errors(),
        )

    cam = await db.get(Camera, job_data.camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")

    job = ProcessingJob(
        camera_id=job_data.camera_id,
        source_uri=job_data.source_uri,
        status=JobStatus.queued,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    job = await db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
