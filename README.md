
# IRIS Task 093 — TenneT Live Grid Stress & EBN Alerts

## Overview

This repository contains a reproducible, staging-only ingestion
pipeline for TenneT-related electricity-grid redispatch observations.

The implementation extracts historical redispatch observations from
a public German transmission-system-operator publication, validates
and normalizes the data, identifies TenneT involvement, and loads
eligible records into an isolated PostgreSQL staging table.

**Important:** The implemented workflow is a historical CSV ingestion
pipeline, not a live streaming integration or a production alerting
system. Missing bottleneck locations, measured curtailed MW and
source-revision handling are documented limitations.

The original NRW Data Center Business Intelligence Platform
documentation is preserved in:

`docs/README_BASE_PROJECT.md`

## 1. Implemented Scope

- Public source-backed redispatch observations
- Source-file and record SHA-256 fingerprints
- CSV validation and UTC timestamp normalization
- Decimal-based MW and MWh parsing
- TenneT requesting/instructing operator classification
- Rejection of malformed source records
- Exact-duplicate detection
- Transactional PostgreSQL ingestion
- Idempotent reruns for identical records
- Staging-only access using restricted credentials
- Dockerized Python application and PostgreSQL/PostGIS
- Automated database initialization
- Unit and PostgreSQL integration tests
- Source-aware operational logging
- Data quality and limitations reporting

Only the `iris_staging` schema is used for the Task 093 data
pipeline. No production database or `iris_core` write is required.

## 2. Data Source and Provenance

Primary source:

Netztransparenz — Redispatch

https://www.netztransparenz.de/en/Ancillary-Services/System-operations/Redispatch

The implemented source is a downloaded historical German redispatch
CSV containing records involving multiple transmission operators.
TenneT-related records are selected using the published requesting
and instructing operator fields.

Input filename:

`data/raw/Redispatch_Daten.csv`

Verified input snapshot:

- Total unique validated records: 462
- TenneT-related records: 402
- Other records excluded from staging: 60
- Rejected records: 0
- Exact duplicate source rows: 0

Verified source SHA-256:

`62fe58ee59cccc3bfa1c6d61812540ea2c7e9c48b64a23475d8dd75f1a8cb6f0`

These counts refer to the verified input snapshot. A different
download or updated publication may produce different results.

### Source acquisition

The CSV was obtained manually from the official publication.

For reproducing the verified run, place the corresponding source
CSV at:

`data/raw/Redispatch_Daten.csv`

The file must retain its expected semicolon-delimited structure
and required German column names.

The download is not automated, and the source may be updated by
its publisher. A fresh download is therefore not guaranteed to
have the same SHA-256 or record counts.

Redistribution rights for the raw CSV must be checked before
including it in a publicly accessible repository.

### Additional investigated sources

The Dutch congestion-capacity publication and ENTSO-E
Redispatching Internal data were also investigated.

An ENTSO-E export for TenneT Germany provided 15 redispatch
instances and 252 interval records on the examined date.
The affected-asset location fields were empty for those records.

ENTSO-E observations were not automatically merged with the
primary Netztransparenz records because event-level correspondence
has not been established.

## 3. Technology Stack

- Python 3.12
- SQLAlchemy
- psycopg 3
- python-dotenv
- PostgreSQL 17
- PostGIS
- Docker and Docker Compose
- Python unittest

The dedicated ETL dependencies are pinned in
`requirements-tennet.txt`.

## 4. Architecture

```text
Official Redispatch CSV
        |
        v
CSV Extractor
- Column validation
- Timestamp normalization
- Decimal parsing
- SHA-256 provenance
- Duplicate and malformed-row detection
        |
        v
TenneT Transformer
- Requesting operator classification
- Instructing operator classification
- Direction and test-run flags
        |
        v
Staging Loader
- Preview by default
- Transactional insertion
- Duplicate conflict handling
- Source-aware logging
        |
        v
PostgreSQL / PostGIS
iris_staging.grid_congestion_timeseries
```

The Python application runs as an unprivileged container process.
Database ingestion uses the restricted `iris_tennet_ingest` role.

## 5. Project Files

```text
app/
  database/
    staging_connection.py
    staging_models.py
  extractors/
    tennet_redispatch_extractor.py
  transformers/
    tennet_redispatch_transformer.py
  loaders/
    tennet_redispatch_loader.py
  services/
    tennet_quality_report.py

docker/
  postgres/
    init/
      20_iris_staging_init.sh

tests/
  test_tennet_pipeline.py
  test_tennet_db_integration.py

data/
  raw/
    Redispatch_Daten.csv

reports/
  tennet_quality_report.json

Dockerfile
docker-compose.yml
.dockerignore
.env.example
requirements-tennet.txt
```

The repository also contains pre-existing base-project modules
which are separate from this Task 093 ingestion workflow.

## 6. Prerequisites

- Docker Desktop with Docker Compose
- Git
- The required official source CSV
- Available local TCP port 55433

Python installation on the host is optional when using the
Docker workflow.

## 7. Environment Configuration

Create a local environment file.

PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace both password placeholders with strong,
different local passwords.

Expected configuration:

```dotenv
IRIS_POSTGRES_DB=iris_tennet_staging
IRIS_POSTGRES_USER=iris_staging_owner
IRIS_POSTGRES_PASSWORD=REPLACE_WITH_A_STRONG_LOCAL_PASSWORD

IRIS_INGEST_USER=iris_tennet_ingest
IRIS_INGEST_PASSWORD=REPLACE_WITH_A_DIFFERENT_STRONG_PASSWORD
```

Do not commit `.env`.

The application database user is distinct from the PostgreSQL
initialization user.

## 8. Docker Setup

Validate the configuration:

```powershell
docker compose config --quiet
```

Start the isolated PostgreSQL database:

```powershell
docker compose up -d postgres
```

On a fresh PostgreSQL volume, the initialization script creates
the staging schema, table, index and restricted ingestion role.

Initialization scripts are not rerun automatically when an
already-initialized volume is restarted.

The database runs on:

- Docker internal address: `postgres:5432`
- Host address: `127.0.0.1:55433`

The ETL application is enabled through the `pipeline` profile
and normally runs as an on-demand container.

Do not use `docker compose down -v` on an environment containing
data that must be retained.

## 9. Run the ETL Pipeline

### Preview without database writes

```powershell
docker compose run --rm --build app
```

Preview mode validates the source, identifies TenneT-related
observations, and displays ingestion counts.

It does not insert observations into PostgreSQL.

### Apply ingestion

```powershell
docker compose run --rm app python -m app.loaders.tennet_redispatch_loader --apply
```

The loader uses the restricted staging database connection.

It inserts new source-content hashes and skips existing hashes.
The insert operation runs inside a PostgreSQL transaction.

### Rerun behavior

For the verified snapshot, after the first successful ingestion:

```text
Prepared records: 402
Records before ingestion: 402
New records inserted: 0
Existing records skipped: 402
Records after ingestion: 402
```

This demonstrates idempotency for unchanged source records.

It does not establish stable provider event identity across
revised or corrected publications.

## 10. Database Schema

Destination:

`iris_staging.grid_congestion_timeseries`

The table has 22 columns.

Key fields include:

| Field | Description |
|---|---|
| record_sha256 | Content-based record primary key |
| source_file_sha256 | Source snapshot fingerprint |
| source_url | Public source reference |
| start_utc | Interval start timestamp |
| end_utc | Interval end timestamp |
| requesting_operator | Requesting transmission operator |
| instructing_operator | Instructing transmission operator |
| affected_facility | Facility named by the source |
| direction | Reported redispatch direction |
| reason | Reported reason |
| average_power_mw | Published average power adjustment |
| maximum_power_mw | Published maximum power adjustment |
| total_energy_mwh | Published energy amount |
| tennet_requested | TenneT involved as requesting operator |
| tennet_instructed | TenneT involved as instructing operator |
| tennet_related | TenneT involved in either role |
| generation_reduction | Direction classified as reduction |
| test_run | Event classified as test operation |
| bottleneck_location | Nullable; location not established |
| curtailed_mw | Nullable; measured curtailed MW not established |
| ingested_at | Database ingestion timestamp |

The database enforces:

- A primary key on `record_sha256`
- Nonnegative average and maximum MW values
- End timestamp later than start timestamp
- An index on `start_utc`

### Important measurement distinction

Published redispatch power adjustment in MW is not automatically
equivalent to measured renewable generation curtailment.

The current workflow therefore does not assign
`average_power_mw` or `maximum_power_mw` to `curtailed_mw`.

Similarly, a named affected facility is not necessarily the
actual constrained network element or bottleneck location.

## 11. Example SQL Queries

### Total staged observations

```sql
SELECT COUNT(*)
FROM iris_staging.grid_congestion_timeseries;
```

### Check unique record fingerprints

```sql
SELECT
    COUNT(*) AS total_records,
    COUNT(DISTINCT record_sha256) AS unique_records
FROM iris_staging.grid_congestion_timeseries;
```

### Validate intervals

```sql
SELECT COUNT(*) AS invalid_intervals
FROM iris_staging.grid_congestion_timeseries
WHERE end_utc <= start_utc;
```

### Inspect representative observations

```sql
SELECT
    start_utc,
    end_utc,
    requesting_operator,
    instructing_operator,
    affected_facility,
    direction,
    reason,
    average_power_mw,
    maximum_power_mw,
    total_energy_mwh
FROM iris_staging.grid_congestion_timeseries
ORDER BY start_utc
LIMIT 10;
```

### Check missing data

```sql
SELECT
    COUNT(*) AS total_records,
    COUNT(*) FILTER (
        WHERE bottleneck_location IS NULL
    ) AS missing_bottleneck_location,
    COUNT(*) FILTER (
        WHERE curtailed_mw IS NULL
    ) AS missing_curtailed_mw
FROM iris_staging.grid_congestion_timeseries;
```

Queries can be executed with `psql` inside the PostgreSQL
container.

## 12. Automated Tests

Run all automated tests in Docker:

```powershell
docker compose run --rm --build app python -m unittest discover -s tests -p "test_*.py" -v
```

Verified result:

```text
Ran 14 tests

OK
```

Coverage includes:

- Valid CSV observations
- Missing or malformed CSV fields
- Invalid dates and time intervals
- Unsupported timezones
- Invalid adjustment directions
- Negative MW values
- Source duplicate detection
- TenneT classification
- Staging field mapping
- PostgreSQL duplicate handling
- Explicit transaction rollback
- Automatic rollback after a PostgreSQL constraint violation

The database integration tests require an initialized PostgreSQL
service and the restricted ingestion credentials.

Synthetic test records are rolled back, leaving the original
staging observations unchanged.

## 13. Quality Report

A source quality report is generated by the project module:

`app/services/tennet_quality_report.py`

The verified report is stored at:

`reports/tennet_quality_report.json`

For the evaluated input snapshot:

| Metric | Result |
|---|---:|
| Valid source observations | 462 |
| Source duplicates | 0 |
| Rejected observations | 0 |
| TenneT-related observations | 402 |
| Staged observations | 402 |
| Missing bottleneck locations | 402 |
| Missing measured curtailed MW | 402 |
| Invalid stored time intervals | 0 |

These metrics describe the evaluated snapshot, not a
continuously refreshed live dataset.

## 14. Operational Logging and Fault Handling

The loader records operational events including:

- Source validation and source SHA-256
- Duplicate and rejected-record counts
- TenneT classification counts
- Preview completion
- Ingestion start and completion
- Source extraction failures
- Database ingestion failures

Logs are emitted to the process output streams and can be
collected from Docker execution.

Rejected input records cause the loader to abort before
database ingestion.

Database insertion occurs inside a transaction. A database
constraint violation rolls back the failed transaction.

The verified tests demonstrate rollback behavior for a
controlled constraint-error scenario.

## 15. Known Limitations and Open Requirements

### Historical, not live

The implemented source is a manually downloaded historical CSV.
There is no authenticated live TenneT API integration, scheduled
source retrieval, or continuous streaming ingestion.

### Bottleneck locations unavailable

The examined primary CSV does not identify exact constrained
network elements or their geographic coordinates.

The available facility field must not be presented as a
verified grid bottleneck location.

### Measured curtailed MW unavailable

The source provides redispatch power-adjustment quantities,
but not a separately verified measured curtailed-MW field.

Accordingly, `curtailed_mw` remains NULL.

### Source event corrections

`record_sha256` represents content identity, not an official
event identifier.

A corrected observation with changed contents may receive a
new hash and be stored as another row.

The workflow does not automatically reconcile provider
corrections or determine which revision is authoritative.

### Data availability and redistribution

The source snapshot must be supplied to reproduce the
exact verified record counts.

Source accessibility, updates, and redistribution permission
must be checked before final publication.

### EBN alerts and downstream BESS screening

This implementation delivers staging observations for
downstream analysis. It does not implement a separate
production alert engine or BESS investment-screening model.

No alert threshold or EBN-specific output is assumed
without an explicit specification.

## 16. Validation Summary

The latest verified development run demonstrated:

- Python image successfully built inside Docker
- PostgreSQL initialized automatically using an isolated
  fresh test volume
- Restricted ingestion permissions verified
- 14 automated tests passed inside Docker
- 402 unique source records present in the staging table
- No invalid stored time intervals
- Identical-source rerun inserted zero duplicate records
- Transaction rollback tested after a constraint violation
- Existing staging observations preserved

These findings apply to the tested environment and snapshot.

A complete fresh-volume ingestion run and final source
redistribution review remain outstanding acceptance checks.

## 17. Submission Notes

Before submission:

1. Verify the included source-data usage rights.
2. Ensure the verified source input or reproducible retrieval
   instructions are available to reviewers.
3. Confirm `.env` and passwords are not committed.
4. Run the complete Docker test suite.
5. Review the quality report and documented limitations.
6. Verify the Git repository contains the intended Task 093
   implementation and no temporary local files.

This implementation prioritizes reproducibility, provenance,
staging isolation, honest data semantics, and preservation of
original source observations.
