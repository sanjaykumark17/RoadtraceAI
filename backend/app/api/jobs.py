from pathlib import Path
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.config import settings
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
    recorded_start_at: Optional[str] = None

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
        recorded_start_at = body.get("recorded_start_at")
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
        recorded_start_at = form.get("recorded_start_at")
        video_file = form.get("video")
        if video_file and hasattr(video_file, "filename") and video_file.filename:
            # Actually save uploaded video to configured upload directory
            upload_dir = Path(settings.upload_dir).resolve()
            upload_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(video_file.filename).name
            unique_name = f"{uuid.uuid4().hex}_{safe_name}"
            saved_path = upload_dir / unique_name
            content = await video_file.read()
            with open(saved_path, "wb") as f:
                f.write(content)
            source_uri = str(saved_path)
    else:
        try:
            body = await request.json()
            camera_id = body.get("camera_id")
            source_uri = body.get("source_uri", "")
            recorded_start_at = body.get("recorded_start_at")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="unsupported content type or invalid payload",
            )

    # Validate source_uri: allowlisted RTSP URLs or files within upload_dir
    source_lower = source_uri.lower()
    if source_lower.startswith(("rtsp://", "rtsps://")):
        if settings.rtsp_allowlist:
            if not any(source_uri.startswith(allowed) for allowed in settings.rtsp_allowlist):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="RTSP source_uri is not on the allowlist",
                )
    else:
        upload_dir = Path(settings.upload_dir).resolve()
        try:
            file_path = Path(source_uri).resolve()
            if not file_path.is_relative_to(upload_dir) or not file_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="source_uri must be an allowlisted rtsp:// URL or an existing file inside the upload directory",
                )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="source_uri must be an allowlisted rtsp:// URL or an existing file inside the upload directory",
            )

    try:
        job_data = JobCreate(
            camera_id=camera_id,
            source_uri=source_uri,
            recorded_start_at=recorded_start_at,
        )
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
        recorded_start_at=job_data.recorded_start_at,
        status=JobStatus.queued,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("", response_model=List[JobOut])
async def list_jobs(
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "operator")),
):
    result = await db.execute(select(ProcessingJob).order_by(ProcessingJob.id.desc()))
    return result.scalars().all()


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
