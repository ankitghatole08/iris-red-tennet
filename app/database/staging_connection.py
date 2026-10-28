
"""Restricted connection to the isolated IRIS staging database.

Supports:
- Windows local development
- Docker Compose application containers

Never connects to iris_core or an unrestricted production database.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL


EXPECTED_DATABASE = "iris_tennet_staging"
EXPECTED_USER = "iris_tennet_ingest"

# Only explicitly approved local/Docker database endpoints.
ALLOWED_ENDPOINTS = {
    "127.0.0.1": 55433,
    "postgres": 5432,
}


def create_staging_engine() -> Engine:
    """Create and verify a restricted staging-only connection."""

    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"

    # Local Windows development uses .env.
    # Docker Compose injects environment variables directly.
    if env_path.is_file():
        load_dotenv(
            dotenv_path=env_path,
            override=False,
        )

    database = os.getenv("IRIS_POSTGRES_DB")
    username = os.getenv("IRIS_INGEST_USER")
    password = os.getenv("IRIS_INGEST_PASSWORD")

    host = os.getenv("IRIS_DB_HOST", "127.0.0.1")

    if database != EXPECTED_DATABASE:
        raise RuntimeError("Unexpected database name.")

    if username != EXPECTED_USER:
        raise RuntimeError("Unexpected database user.")

    if not password:
        raise RuntimeError("Ingestion password is missing.")

    if host not in ALLOWED_ENDPOINTS:
        raise RuntimeError(
            f"Unauthorized database host: {host}"
        )

    expected_port = ALLOWED_ENDPOINTS[host]

    try:
        port = int(
            os.getenv("IRIS_DB_PORT", str(expected_port))
        )
    except ValueError as exc:
        raise RuntimeError(
            "Invalid database port."
        ) from exc

    if port != expected_port:
        raise RuntimeError(
            "Unexpected database port."
        )

    url = URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )

    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT
                        current_database(),
                        current_user,
                        has_schema_privilege(
                            current_user,
                            'iris_staging',
                            'USAGE'
                        ),
                        has_schema_privilege(
                            current_user,
                            'iris_staging',
                            'CREATE'
                        ),
                        has_schema_privilege(
                            current_user,
                            'public',
                            'CREATE'
                        ),
                        has_table_privilege(
                            current_user,
                            'iris_staging.grid_congestion_timeseries',
                            'SELECT'
                        ),
                        has_table_privilege(
                            current_user,
                            'iris_staging.grid_congestion_timeseries',
                            'INSERT'
                        ),
                        has_table_privilege(
                            current_user,
                            'iris_staging.grid_congestion_timeseries',
                            'UPDATE'
                        ),
                        has_table_privilege(
                            current_user,
                            'iris_staging.grid_congestion_timeseries',
                            'DELETE'
                        )
                """)
            ).one()

            (
                connected_database,
                connected_user,
                can_use_schema,
                can_create_in_staging,
                can_create_in_public,
                can_select,
                can_insert,
                can_update,
                can_delete,
            ) = result

            if (
                connected_database != EXPECTED_DATABASE
                or connected_user != EXPECTED_USER
            ):
                raise RuntimeError(
                    "Database identity verification failed."
                )

            if not all((
                can_use_schema,
                can_select,
                can_insert,
                can_update,
            )):
                raise RuntimeError(
                    "Required staging permissions are missing."
                )

            if any((
                can_create_in_staging,
                can_create_in_public,
                can_delete,
            )):
                raise RuntimeError(
                    "Unsafe staging permissions detected."
                )

    except Exception:
        engine.dispose()
        raise

    return engine


if __name__ == "__main__":
    engine = create_staging_engine()

    print("Restricted staging connection verified.")
    print("Database:", EXPECTED_DATABASE)
    print("User:", EXPECTED_USER)

    engine.dispose()
