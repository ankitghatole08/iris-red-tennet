
"""Automated tests for IRIS Task 093 TenneT data processing.

These tests use temporary CSV fixtures.
They do not connect to or modify PostgreSQL.
"""

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.extractors.tennet_redispatch_extractor import (
    REQUIRED_COLUMNS,
    extract,
)
from app.transformers.tennet_redispatch_transformer import (
    classify_events,
)
from app.loaders.tennet_redispatch_loader import (
    prepare_database_record,
)


def valid_source_row():
    """Return one representative synthetic test record."""

    return {
        "BEGINN_DATUM": "01.10.2026",
        "BEGINN_UHRZEIT": "09:00",
        "ZEITZONE_VON": "UTC",
        "ENDE_DATUM": "01.10.2026",
        "ENDE_UHRZEIT": "10:00",
        "ZEITZONE_BIS": "UTC",
        "GRUND_DER_MASSNAHME": "Strombedingter Redispatch",
        "RICHTUNG": "Wirkleistungseinspeisung reduzieren",
        "MITTLERE_LEISTUNG_MW": "12,50",
        "MAXIMALE_LEISTUNG_MW": "15,00",
        "GESAMTE_ARBEIT_MWH": "12,50",
        "ANWEISENDER_UENB": "TenneT DE",
        "ANFORDERNDER_UENB": "Amprion & TenneT DE",
        "BETROFFENE_ANLAGE": "Test Facility",
        "PRIMAERENERGIEART": "Erneuerbar",
    }


def extract_fixture(rows, columns=None):
    """Write temporary source data and run the real extractor."""

    columns = list(columns or REQUIRED_COLUMNS)

    with tempfile.TemporaryDirectory() as directory:
        csv_path = Path(directory) / "test_redispatch.csv"

        with csv_path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns,
                delimiter=";",
            )

            writer.writeheader()

            for row in rows:
                writer.writerow({
                    column: row.get(column, "")
                    for column in columns
                })

        return extract(csv_path)


class TestTenneTPipeline(unittest.TestCase):
    """Validate extraction, classification and record preparation."""

    def test_valid_record(self):
        events, rejected, duplicates, checksum = extract_fixture(
            [valid_source_row()]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(duplicates, 0)
        self.assertEqual(len(checksum), 64)

        event = events[0]

        self.assertEqual(
            event["start_utc"],
            "2026-10-01T09:00:00+00:00",
        )

        self.assertEqual(
            Decimal(event["average_power_mw"]),
            Decimal("12.50"),
        )

    def test_duplicate_records(self):
        row = valid_source_row()

        events, rejected, duplicates, _ = extract_fixture(
            [row, row]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(duplicates, 1)
        self.assertEqual(len(rejected), 0)

    def test_missing_required_column(self):
        columns = [
            column
            for column in REQUIRED_COLUMNS
            if column != "BEGINN_DATUM"
        ]

        with self.assertRaisesRegex(
            ValueError,
            "Missing required CSV columns",
        ):
            extract_fixture(
                [valid_source_row()],
                columns=columns,
            )

    def test_missing_required_value(self):
        row = valid_source_row()
        row["BETROFFENE_ANLAGE"] = ""

        events, rejected, _, _ = extract_fixture([row])

        self.assertEqual(len(events), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["line"], 2)

    def test_invalid_timestamp(self):
        row = valid_source_row()
        row["BEGINN_DATUM"] = "99.10.2026"

        events, rejected, _, _ = extract_fixture([row])

        self.assertEqual(len(events), 0)
        self.assertEqual(len(rejected), 1)

    def test_invalid_time_interval(self):
        row = valid_source_row()
        row["ENDE_UHRZEIT"] = "08:00"

        events, rejected, _, _ = extract_fixture([row])

        self.assertEqual(len(events), 0)
        self.assertEqual(len(rejected), 1)

    def test_negative_power_rejected(self):
        row = valid_source_row()
        row["MITTLERE_LEISTUNG_MW"] = "-10,50"

        events, rejected, _, _ = extract_fixture([row])

        self.assertEqual(len(events), 0)
        self.assertEqual(len(rejected), 1)

    def test_invalid_direction(self):
        row = valid_source_row()
        row["RICHTUNG"] = "Unknown direction"

        events, rejected, _, _ = extract_fixture([row])

        self.assertEqual(len(events), 0)
        self.assertEqual(len(rejected), 1)

    def test_invalid_timezone(self):
        row = valid_source_row()
        row["ZEITZONE_VON"] = "UNKNOWN"

        events, rejected, _, _ = extract_fixture([row])

        self.assertEqual(len(events), 0)
        self.assertEqual(len(rejected), 1)

    def test_tennet_classification(self):
        events, _, _, _ = extract_fixture(
            [valid_source_row()]
        )

        classified = classify_events(events)
        event = classified[0]

        self.assertTrue(event["tennet_requested"])
        self.assertTrue(event["tennet_instructed"])
        self.assertTrue(event["tennet_related"])
        self.assertTrue(event["generation_reduction"])
        self.assertFalse(event["test_run"])

    def test_non_tennet_classification(self):
        row = valid_source_row()
        row["ANWEISENDER_UENB"] = "50Hertz"
        row["ANFORDERNDER_UENB"] = "Amprion"

        events, _, _, _ = extract_fixture([row])
        classified = classify_events(events)

        self.assertFalse(classified[0]["tennet_related"])

    def test_staging_mapping(self):
        events, _, _, _ = extract_fixture(
            [valid_source_row()]
        )

        classified = classify_events(events)
        record = prepare_database_record(classified[0])

        self.assertEqual(
            record["average_power_mw"],
            Decimal("12.50"),
        )

        self.assertTrue(record["tennet_related"])

        # Source does not establish these measurements.
        self.assertIsNone(record["bottleneck_location"])
        self.assertIsNone(record["curtailed_mw"])


if __name__ == "__main__":
    unittest.main()
