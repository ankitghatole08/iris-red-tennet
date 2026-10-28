
"""Load validated TenneT redispatch observations into IRIS staging.

Default mode: preview only.
Use --apply to write to the isolated staging database.

Operational logging includes source provenance, validation results,
classification summaries, ingestion outcomes, and failures.
"""

import argparse
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.database.staging_connection import create_staging_engine
from app.database.staging_models import GridCongestionTimeSeries
from app.extractors.tennet_redispatch_extractor import extract
from app.transformers.tennet_redispatch_transformer import classify_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILE = PROJECT_ROOT / "data" / "raw" / "Redispatch_Daten.csv"

LOGGER = logging.getLogger("iris_tennet.ingestion")


def prepare_database_record(event):
    """Convert a classified event into staging table fields."""

    return {
        "record_sha256": event["record_sha256"],
        "source_file_sha256": event["source_file_sha256"],
        "source_url": event["source_url"],

        "start_utc": datetime.fromisoformat(event["start_utc"]),
        "end_utc": datetime.fromisoformat(event["end_utc"]),

        "requesting_operator": event["requesting_operator"],
        "instructing_operator": event["instructing_operator"],
        "affected_facility": event["affected_facility"],
        "primary_energy_type": event["primary_energy_type"],

        "direction": event["direction"],
        "reason": event["reason"],

        "average_power_mw": Decimal(event["average_power_mw"]),
        "maximum_power_mw": Decimal(event["maximum_power_mw"]),
        "total_energy_mwh": Decimal(event["total_energy_mwh"]),

        "tennet_requested": event["tennet_requested"],
        "tennet_instructed": event["tennet_instructed"],
        "tennet_related": event["tennet_related"],
        "generation_reduction": event["generation_reduction"],
        "test_run": event["test_run"],

        # These values are not established by the current source.
        # Do not manufacture bottleneck locations or curtailed MW.
        "bottleneck_location": None,
        "curtailed_mw": None,
    }


def load_events(records):
    """Insert new observations in one atomic transaction.

    Existing content hashes are skipped.

    SQLAlchemy commits when the transaction succeeds and rolls
    back automatically if an exception occurs within the block.
    """

    if not records:
        return 0, 0, 0

    engine = create_staging_engine()

    try:
        with engine.begin() as connection:

            before_count = connection.execute(
                select(func.count()).select_from(
                    GridCongestionTimeSeries
                )
            ).scalar_one()

            statement = insert(
                GridCongestionTimeSeries
            ).values(records)

            statement = statement.on_conflict_do_nothing(
                index_elements=["record_sha256"]
            )

            statement = statement.returning(
                GridCongestionTimeSeries.record_sha256
            )

            result = connection.execute(statement)

            inserted_ids = result.scalars().all()
            inserted_count = len(inserted_ids)

            after_count = connection.execute(
                select(func.count()).select_from(
                    GridCongestionTimeSeries
                )
            ).scalar_one()

        return before_count, inserted_count, after_count

    finally:
        engine.dispose()


def main():
    """Validate source data and optionally ingest into staging."""

    parser = argparse.ArgumentParser(
        description="IRIS Task 093 TenneT Redispatch loader"
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert validated records into the staging database",
    )

    args = parser.parse_args()

    # Step 1: Confirm source availability.
    if not SOURCE_FILE.is_file():
        LOGGER.error(
            "event=source_file_missing source_file=%s",
            SOURCE_FILE.name,
        )

        raise FileNotFoundError(
            f"Source CSV not found: {SOURCE_FILE}"
        )

    # Step 2: Extract and validate source observations.
    try:
        events, rejected, duplicates, checksum = extract(
            SOURCE_FILE
        )

    except Exception:
        LOGGER.exception(
            "event=source_extraction_failed source_file=%s",
            SOURCE_FILE.name,
        )
        raise

    print("=== IRIS TASK 093: SOURCE VALIDATION ===")
    print("Source:", SOURCE_FILE.name)
    print("Source SHA-256:", checksum)
    print("Valid unique records:", len(events))
    print("Duplicate source rows:", duplicates)
    print("Rejected records:", len(rejected))

    LOGGER.info(
        "event=source_validation "
        "source_file=%s "
        "source_sha256=%s "
        "valid_records=%d "
        "duplicate_records=%d "
        "rejected_records=%d",
        SOURCE_FILE.name,
        checksum,
        len(events),
        duplicates,
        len(rejected),
    )

    if rejected:
        print("Rejected record samples:", rejected[:5])

        LOGGER.error(
            "event=source_validation_failed "
            "source_file=%s "
            "source_sha256=%s "
            "rejected_records=%d "
            "database_write=aborted",
            SOURCE_FILE.name,
            checksum,
            len(rejected),
        )

        raise RuntimeError(
            "Source validation failed. No records were loaded."
        )

    # Step 3: Classify TenneT involvement.
    classified = classify_events(events)

    tennet_events = [
        event
        for event in classified
        if event["tennet_related"]
    ]

    excluded = len(classified) - len(tennet_events)

    print()
    print("=== TENNET CLASSIFICATION ===")
    print("Total classified:", len(classified))
    print("TenneT-related:", len(tennet_events))
    print("Non-TenneT excluded from staging:", excluded)

    LOGGER.info(
        "event=tennet_classification "
        "source_file=%s "
        "source_sha256=%s "
        "total_records=%d "
        "tennet_related=%d "
        "excluded=%d",
        SOURCE_FILE.name,
        checksum,
        len(classified),
        len(tennet_events),
        excluded,
    )

    # Step 4: Prepare staging records.
    records = [
        prepare_database_record(event)
        for event in tennet_events
    ]

    print()
    print("=== STAGING INGESTION ===")
    print("Prepared records:", len(records))

    if not args.apply:
        print("Mode: PREVIEW ONLY")
        print("No database writes performed.")
        print("Use --apply for database ingestion.")

        LOGGER.info(
            "event=staging_preview_completed "
            "source_file=%s "
            "source_sha256=%s "
            "prepared_records=%d "
            "database_write=false",
            SOURCE_FILE.name,
            checksum,
            len(records),
        )

        return

    # Step 5: Apply ingestion using restricted credentials.
    LOGGER.info(
        "event=staging_ingestion_started "
        "source_file=%s "
        "source_sha256=%s "
        "prepared_records=%d",
        SOURCE_FILE.name,
        checksum,
        len(records),
    )

    try:
        before, inserted, after = load_events(records)

    except Exception:
        LOGGER.exception(
            "event=staging_ingestion_failed "
            "source_file=%s "
            "source_sha256=%s "
            "prepared_records=%d",
            SOURCE_FILE.name,
            checksum,
            len(records),
        )
        raise

    skipped = len(records) - inserted

    print("Mode: APPLY")
    print("Records before ingestion:", before)
    print("New records inserted:", inserted)
    print("Existing records skipped:", skipped)
    print("Records after ingestion:", after)
    print("Staging ingestion completed successfully.")

    LOGGER.info(
        "event=staging_ingestion_completed "
        "source_file=%s "
        "source_sha256=%s "
        "records_before=%d "
        "inserted=%d "
        "skipped=%d "
        "records_after=%d",
        SOURCE_FILE.name,
        checksum,
        before,
        inserted,
        skipped,
        after,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
    )

    main()
