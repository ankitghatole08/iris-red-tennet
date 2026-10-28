
"""Database integration tests for IRIS Task 093.

Uses the isolated staging database and restricted ingestion user.

Tests verify:
- Duplicate-safe insertions.
- Explicit transaction rollback.
- Automatic rollback after a database constraint violation.

All test records are synthetic. No test records are committed.
"""

import hashlib
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.database.staging_connection import create_staging_engine
from app.database.staging_models import GridCongestionTimeSeries


class TestTenneTDatabaseIntegration(unittest.TestCase):
    """Verify PostgreSQL ingestion and transaction safety."""

    def test_duplicate_insert_and_rollback(self):
        """Verify duplicate handling and explicit rollback."""

        engine = create_staging_engine()

        fixture_hash = hashlib.sha256(
            b"IRIS-RED-TENNET-INTEGRATION-TEST-V1"
        ).hexdigest()

        fixture_source_hash = hashlib.sha256(
            b"SYNTHETIC-TEST-FIXTURE"
        ).hexdigest()

        record = {
            "record_sha256": fixture_hash,
            "source_file_sha256": fixture_source_hash,
            "source_url": "fixture://integration-test",

            "start_utc": datetime(
                2026, 10, 1, 9, 0,
                tzinfo=timezone.utc,
            ),
            "end_utc": datetime(
                2026, 10, 1, 10, 0,
                tzinfo=timezone.utc,
            ),

            "requesting_operator": "TenneT DE",
            "instructing_operator": "TenneT DE",
            "affected_facility": "Synthetic Test Facility",
            "primary_energy_type": "Erneuerbar",

            "direction": "Wirkleistungseinspeisung reduzieren",
            "reason": "Strombedingter Redispatch",

            "average_power_mw": Decimal("12.50"),
            "maximum_power_mw": Decimal("15.00"),
            "total_energy_mwh": Decimal("12.50"),

            "tennet_requested": True,
            "tennet_instructed": True,
            "tennet_related": True,
            "generation_reduction": True,
            "test_run": False,

            "bottleneck_location": None,
            "curtailed_mw": None,
        }

        try:
            with engine.connect() as connection:
                transaction = connection.begin()

                try:
                    count_query = select(
                        func.count()
                    ).select_from(
                        GridCongestionTimeSeries
                    )

                    before_count = connection.execute(
                        count_query
                    ).scalar_one()

                    statement = insert(
                        GridCongestionTimeSeries
                    ).values(record)

                    statement = statement.on_conflict_do_nothing(
                        index_elements=["record_sha256"]
                    ).returning(
                        GridCongestionTimeSeries.record_sha256
                    )

                    # First insertion should succeed.
                    first_insert = connection.execute(
                        statement
                    ).scalars().all()

                    # Identical second insertion should be skipped.
                    second_insert = connection.execute(
                        statement
                    ).scalars().all()

                    after_insert_count = connection.execute(
                        count_query
                    ).scalar_one()

                    self.assertEqual(len(first_insert), 1)
                    self.assertEqual(len(second_insert), 0)
                    self.assertEqual(
                        after_insert_count,
                        before_count + 1,
                    )

                finally:
                    # Always undo the test insertion.
                    transaction.rollback()

            # Confirm no synthetic record was persisted.
            with engine.connect() as connection:
                final_count = connection.execute(
                    select(func.count()).select_from(
                        GridCongestionTimeSeries
                    )
                ).scalar_one()

                fixture_count = connection.execute(
                    select(func.count()).select_from(
                        GridCongestionTimeSeries
                    ).where(
                        GridCongestionTimeSeries.record_sha256
                        == fixture_hash
                    )
                ).scalar_one()

                self.assertEqual(final_count, before_count)
                self.assertEqual(fixture_count, 0)

        finally:
            engine.dispose()

    def test_database_error_rolls_back_entire_transaction(self):
        """Verify atomic rollback after a PostgreSQL constraint error.

        Insert one valid synthetic record, then deliberately insert
        an invalid synthetic record in the same transaction.

        The invalid record violates the database constraint:
            end_utc > start_utc

        Both test records must be absent after rollback.
        """

        engine = create_staging_engine()

        valid_hash = hashlib.sha256(
            b"IRIS-RED-TENNET-ATOMIC-VALID-V1"
        ).hexdigest()

        invalid_hash = hashlib.sha256(
            b"IRIS-RED-TENNET-ATOMIC-INVALID-V1"
        ).hexdigest()

        fixture_source_hash = hashlib.sha256(
            b"SYNTHETIC-ATOMICITY-TEST-FIXTURE"
        ).hexdigest()

        valid_record = {
            "record_sha256": valid_hash,
            "source_file_sha256": fixture_source_hash,
            "source_url": "fixture://atomicity-test",

            "start_utc": datetime(
                2026, 10, 2, 9, 0,
                tzinfo=timezone.utc,
            ),
            "end_utc": datetime(
                2026, 10, 2, 10, 0,
                tzinfo=timezone.utc,
            ),

            "requesting_operator": "TenneT DE",
            "instructing_operator": "TenneT DE",
            "affected_facility": "Synthetic Atomicity Test",
            "primary_energy_type": "Erneuerbar",

            "direction": "Wirkleistungseinspeisung reduzieren",
            "reason": "Strombedingter Redispatch",

            "average_power_mw": Decimal("10.00"),
            "maximum_power_mw": Decimal("12.00"),
            "total_energy_mwh": Decimal("10.00"),

            "tennet_requested": True,
            "tennet_instructed": True,
            "tennet_related": True,
            "generation_reduction": True,
            "test_run": False,

            "bottleneck_location": None,
            "curtailed_mw": None,
        }

        # Create an invalid record with a unique primary key.
        # The end time is earlier than the start time.
        invalid_record = {
            **valid_record,
            "record_sha256": invalid_hash,
            "start_utc": datetime(
                2026, 10, 2, 11, 0,
                tzinfo=timezone.utc,
            ),
            "end_utc": datetime(
                2026, 10, 2, 10, 0,
                tzinfo=timezone.utc,
            ),
        }

        fixture_hashes = [valid_hash, invalid_hash]

        count_query = select(
            func.count()
        ).select_from(
            GridCongestionTimeSeries
        )

        fixture_count_query = select(
            func.count()
        ).select_from(
            GridCongestionTimeSeries
        ).where(
            GridCongestionTimeSeries.record_sha256.in_(
                fixture_hashes
            )
        )

        try:
            # Establish the database state before the test.
            with engine.connect() as connection:
                before_count = connection.execute(
                    count_query
                ).scalar_one()

                existing_fixtures = connection.execute(
                    fixture_count_query
                ).scalar_one()

                self.assertEqual(existing_fixtures, 0)

            # A database error must escape the transaction context.
            # SQLAlchemy will then automatically roll back.
            with self.assertRaises(IntegrityError) as error:
                with engine.begin() as connection:

                    # This record is valid and initially inserts.
                    connection.execute(
                        insert(
                            GridCongestionTimeSeries
                        ).values(valid_record)
                    )

                    # PostgreSQL rejects this second record.
                    connection.execute(
                        insert(
                            GridCongestionTimeSeries
                        ).values(invalid_record)
                    )

            # Verify the expected database constraint failed.
            self.assertIn(
                "ck_grid_congestion_valid_interval",
                str(error.exception),
            )

            # Verify neither synthetic record was committed.
            with engine.connect() as connection:
                final_count = connection.execute(
                    count_query
                ).scalar_one()

                remaining_fixtures = connection.execute(
                    fixture_count_query
                ).scalar_one()

                self.assertEqual(final_count, before_count)
                self.assertEqual(remaining_fixtures, 0)

        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
