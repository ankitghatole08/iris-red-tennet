
#!/usr/bin/env bash
set -Eeuo pipefail

# IRIS Task 093
# PostgreSQL staging initialization.
#
# Runs only when the PostgreSQL Docker volume is initialized
# for the first time.
#
# Never creates or modifies iris_core.

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${IRIS_INGEST_USER:?IRIS_INGEST_USER is required}"
: "${IRIS_INGEST_PASSWORD:?IRIS_INGEST_PASSWORD is required}"

# Fail closed if this script is pointed at an unexpected database.
if [[ "${POSTGRES_DB}" != "iris_tennet_staging" ]]; then
    echo "ERROR: Unexpected database name." >&2
    exit 1
fi

if [[ "${IRIS_INGEST_USER}" != "iris_tennet_ingest" ]]; then
    echo "ERROR: Unexpected ingestion role." >&2
    exit 1
fi

echo "Initializing isolated IRIS staging database..."

psql \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" \
    --set ON_ERROR_STOP=1 \
    --set "ingest_role=${IRIS_INGEST_USER}" \
    --set "ingest_password=${IRIS_INGEST_PASSWORD}" \
    <<'SQL'

-- ---------------------------------------------------------
-- 1. Create restricted ingestion role if absent.
-- ---------------------------------------------------------

SELECT format(
    'CREATE ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'ingest_role',
    :'ingest_password'
)
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = :'ingest_role'
)
\gexec

-- ---------------------------------------------------------
-- 2. Create isolated staging schema.
-- ---------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS iris_staging;

-- ---------------------------------------------------------
-- 3. Create staging table.
-- Matches verified PostgreSQL schema dump.
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS iris_staging.grid_congestion_timeseries (
    record_sha256 VARCHAR(64) NOT NULL,
    source_file_sha256 VARCHAR(64) NOT NULL,
    source_url TEXT NOT NULL,

    start_utc TIMESTAMPTZ NOT NULL,
    end_utc TIMESTAMPTZ NOT NULL,

    requesting_operator TEXT NOT NULL,
    instructing_operator TEXT NOT NULL,
    affected_facility TEXT NOT NULL,
    primary_energy_type TEXT NOT NULL,

    direction TEXT NOT NULL,
    reason TEXT NOT NULL,

    average_power_mw NUMERIC(18,4) NOT NULL,
    maximum_power_mw NUMERIC(18,4) NOT NULL,
    total_energy_mwh NUMERIC(18,4) NOT NULL,

    tennet_requested BOOLEAN NOT NULL,
    tennet_instructed BOOLEAN NOT NULL,
    tennet_related BOOLEAN NOT NULL,
    generation_reduction BOOLEAN NOT NULL,
    test_run BOOLEAN NOT NULL,

    bottleneck_location TEXT,
    curtailed_mw NUMERIC(18,4),

    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT grid_congestion_timeseries_pkey
        PRIMARY KEY (record_sha256),

    CONSTRAINT ck_grid_congestion_average_power
        CHECK (average_power_mw >= 0),

    CONSTRAINT ck_grid_congestion_maximum_power
        CHECK (maximum_power_mw >= 0),

    CONSTRAINT ck_grid_congestion_valid_interval
        CHECK (end_utc > start_utc)
);

-- ---------------------------------------------------------
-- 4. Create timestamp index.
-- ---------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_grid_congestion_start_utc
ON iris_staging.grid_congestion_timeseries (start_utc);

-- ---------------------------------------------------------
-- 5. Restrict database permissions.
-- ---------------------------------------------------------

-- Prevent ordinary users from creating objects in public.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- No unrestricted access to staging.
REVOKE ALL ON SCHEMA iris_staging FROM PUBLIC;

-- Explicitly assign ingestion permissions.
REVOKE ALL ON SCHEMA iris_staging FROM :"ingest_role";

GRANT USAGE
ON SCHEMA iris_staging
TO :"ingest_role";

REVOKE ALL
ON TABLE iris_staging.grid_congestion_timeseries
FROM PUBLIC;

REVOKE ALL
ON TABLE iris_staging.grid_congestion_timeseries
FROM :"ingest_role";

GRANT SELECT, INSERT, UPDATE
ON TABLE iris_staging.grid_congestion_timeseries
TO :"ingest_role";

-- ---------------------------------------------------------
-- 6. Verify structure.
-- ---------------------------------------------------------

SELECT
    table_schema,
    table_name
FROM information_schema.tables
WHERE table_schema = 'iris_staging'
  AND table_name = 'grid_congestion_timeseries';

SQL

echo "IRIS staging initialization completed successfully."
