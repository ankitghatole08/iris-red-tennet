
"""Generate a deterministic quality report for the TenneT redispatch source data.

Uses real source observations. Does not modify PostgreSQL.
"""

import json
import logging
from collections import Counter
from pathlib import Path

from app.extractors.tennet_redispatch_extractor import (
    SOURCE_URL,
    extract,
)
from app.transformers.tennet_redispatch_transformer import (
    classify_events,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_FILE = (
    PROJECT_ROOT / "data" / "raw" / "Redispatch_Daten.csv"
)

REPORT_FILE = (
    PROJECT_ROOT / "reports" / "tennet_quality_report.json"
)

logger = logging.getLogger("iris.tennet.quality")


def build_quality_report(source_file: Path) -> dict:
    """Assess source validity, TenneT coverage and known gaps."""

    if not source_file.is_file():
        raise FileNotFoundError(
            f"Source file not found: {source_file}"
        )

    events, rejected, duplicates, checksum = extract(
        source_file
    )

    logger.info(
        "Source=%s file=%s sha256=%s",
        SOURCE_URL,
        source_file.name,
        checksum,
    )

    classified = classify_events(events)

    tennet_events = [
        event
        for event in classified
        if event["tennet_related"]
    ]

    source_rows = len(events) + len(rejected) + duplicates

    requesting_count = sum(
        event["tennet_requested"]
        for event in classified
    )

    instructing_count = sum(
        event["tennet_instructed"]
        for event in classified
    )

    both_count = sum(
        event["tennet_requested"]
        and event["tennet_instructed"]
        for event in classified
    )

    non_test_reductions = sum(
        event["tennet_requested"]
        and event["generation_reduction"]
        and not event["test_run"]
        for event in classified
    )

    start_times = [
        event["start_utc"]
        for event in tennet_events
    ]

    end_times = [
        event["end_utc"]
        for event in tennet_events
    ]

    reason_counts = Counter(
        event["reason"]
        for event in tennet_events
    )

    report = {
        "assignment_id": "IRIS-RED-TENNET",
        "source": {
            "filename": source_file.name,
            "publication_url": SOURCE_URL,
            "sha256": checksum,
            "file_size_bytes": source_file.stat().st_size,
            "retrieval": "Manual official CSV download",
        },
        "source_validation": {
            "input_rows": source_rows,
            "valid_unique_rows": len(events),
            "duplicate_rows": duplicates,
            "rejected_rows": len(rejected),
            "rejection_details": rejected,
        },
        "tennet_classification": {
            "requested_rows": requesting_count,
            "instructed_rows": instructing_count,
            "both_roles_rows": both_count,
            "tennet_related_unique_rows": len(tennet_events),
            "non_tennet_rows": (
                len(classified) - len(tennet_events)
            ),
            "requested_non_test_reduction_rows": (
                non_test_reductions
            ),
        },
        "coverage": {
            "earliest_start_utc": (
                min(start_times) if start_times else None
            ),
            "latest_end_utc": (
                max(end_times) if end_times else None
            ),
            "affected_facility_available_rows": sum(
                bool(event["affected_facility"])
                for event in tennet_events
            ),
            "bottleneck_location_available_rows": 0,
            "measured_curtailed_mw_available_rows": 0,
        },
        "tennet_reason_counts": dict(reason_counts),
        "known_limitations": [
            (
                "Affected facility names do not establish "
                "actual grid bottleneck locations."
            ),
            (
                "Redispatch power adjustments are not "
                "automatically equivalent to measured "
                "electricity curtailment."
            ),
            (
                "The source is a historical CSV download; "
                "automatic source retrieval is not yet verified."
            ),
            (
                "The row content hash is not a guaranteed "
                "permanent real-world event identifier."
            ),
            (
                "Duplicate source row counts are available, "
                "but duplicate line numbers are not retained."
            ),
        ],
    }

    if rejected:
        logger.warning(
            "Source=%s rejected_rows=%d",
            source_file.name,
            len(rejected),
        )

    logger.info(
        "Validated=%d TenneT_related=%d duplicates=%d",
        len(events),
        len(tennet_events),
        duplicates,
    )

    return report


def main() -> None:
    """Generate a reproducible JSON quality report."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        report = build_quality_report(SOURCE_FILE)

        REPORT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        REPORT_FILE.write_text(
            json.dumps(
                report,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

    except Exception:
        logger.exception("Quality report generation failed")
        raise

    print("\n=== IRIS TASK 093: QUALITY REPORT ===")
    print("Source:", report["source"]["filename"])
    print(
        "Input rows:",
        report["source_validation"]["input_rows"],
    )
    print(
        "Valid unique rows:",
        report["source_validation"]["valid_unique_rows"],
    )
    print(
        "Duplicate rows:",
        report["source_validation"]["duplicate_rows"],
    )
    print(
        "Rejected rows:",
        report["source_validation"]["rejected_rows"],
    )
    print(
        "TenneT-related rows:",
        report["tennet_classification"][
            "tennet_related_unique_rows"
        ],
    )
    print(
        "Missing bottleneck locations:",
        report["tennet_classification"][
            "tennet_related_unique_rows"
        ] - report["coverage"][
            "bottleneck_location_available_rows"
        ],
    )
    print(
        "Missing measured curtailed MW:",
        report["tennet_classification"][
            "tennet_related_unique_rows"
        ] - report["coverage"][
            "measured_curtailed_mw_available_rows"
        ],
    )
    print("Report saved:", REPORT_FILE)


if __name__ == "__main__":
    main()
