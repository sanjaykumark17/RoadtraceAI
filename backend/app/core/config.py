from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RT_", env_file=".env")

    # environment
    environment: str = "development"

    # database
    database_url: str = "postgresql+asyncpg://roadtrace:roadtrace@localhost:5432/roadtrace"
    database_url_sync: str = "postgresql+psycopg2://roadtrace:roadtrace@localhost:5432/roadtrace"

    # detection
    input_size: int = 640
    vehicle_conf: float = 0.45
    nms_iou: float = 0.50
    yolo_weights: str = "yolov8m.pt"
    plate_weights: str = "ml/weights/plate_yolov8s.pt"

    # uploads & video sources
    upload_dir: str = "uploads"
    snapshots_dir: str = "snapshots"
    rtsp_allowlist: list[str] = []

    # image preprocessing
    blur_tau: int = 100
    clahe_clip_limit: float = 2.0
    clahe_tile_grid: tuple[int, int] = (8, 8)
    bilateral_d: int = 9
    bilateral_sigma_color: float = 75.0
    bilateral_sigma_space: float = 75.0

    # plate OCR
    plate_regex: str = r"^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$"
    ocr_vote_min_frames: int = 5
    ocr_vote_max_frames: int = 15
    levenshtein_max: int = 2

    # travel-path validation
    v_max_kmh: float = 150.0
    earth_radius_km: float = 6371.0

    # OSRM road snapping & routing
    osrm_url: str = "http://localhost:5000"
    osrm_timeout: float = 2.0

    # auth
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    roles: list[str] = ["admin", "operator", "viewer"]
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    frontend_url: str = ""
    auth_rate_limit_per_minute: int = 60
    api_rate_limit_per_minute: int = 120
    auth_rate_limit_enabled: bool = True
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        if self.environment != "development" and self.secret_key == "change-me-in-production":
            raise ValueError("Default secret key is not allowed outside development environment")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        combined = set()
        for source in (self.cors_origins, self.frontend_url):
            if not source:
                continue
            for item in source.split(","):
                cleaned = item.strip()
                if cleaned and cleaned != "*":
                    combined.add(cleaned)
        return list(combined)

    # worker settings
    worker_concurrency: int = 1
    worker_poll_interval: float = 1.0
    snapshots_dir: str = "snapshots"


settings = Settings()

