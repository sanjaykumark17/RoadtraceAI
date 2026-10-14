import os
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

os.environ.setdefault("RT_ADMIN_PASSWORD", "test-admin-pass-987")
os.environ.setdefault("RT_OPERATOR_PASSWORD", "test-operator-pass-654")
os.environ.setdefault("RT_VIEWER_PASSWORD", "test-viewer-pass-321")

TEST_ADMIN_PASSWORD = os.environ["RT_ADMIN_PASSWORD"]
TEST_OPERATOR_PASSWORD = os.environ["RT_OPERATOR_PASSWORD"]
TEST_VIEWER_PASSWORD = os.environ["RT_VIEWER_PASSWORD"]


@pytest.fixture(scope="session", autouse=True)
def run_db_migrations():
    """Ensure database schema, extensions, and tables exist before any tests run."""
    sync_url = os.environ.get(
        "RT_DATABASE_URL_SYNC",
        "postgresql+psycopg2://roadtrace:roadtrace@localhost:5432/roadtrace",
    )
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini = backend_dir / "alembic.ini"

    try:
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS fuzzystrmatch"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.commit()
    except Exception as e:
        print(f"Extension creation notice: {e}")

    if alembic_ini.exists():
        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("sqlalchemy.url", sync_url)
        try:
            command.upgrade(cfg, "head")
        except Exception as e:
            print(f"Alembic migration notice: {e}")

