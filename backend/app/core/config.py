from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RT_", env_file=".env")

    # database
    database_url: str = "postgresql+asyncpg://roadtrace:roadtrace@localhost:5432/roadtrace"
    database_url_sync: str = "postgresql+psycopg2://roadtrace:roadtrace@localhost:5432/roadtrace"

    # detection
    input_size: int = 640
    vehicle_conf: float = 0.45
    nms_iou: float = 0.50

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

    # auth
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    roles: list[str] = ["admin", "operator", "viewer"]


settings = Settings()
