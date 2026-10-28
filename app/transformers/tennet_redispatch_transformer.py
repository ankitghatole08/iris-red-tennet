
"""Classify official redispatch observations involving TenneT."""

from pathlib import Path

from app.extractors.tennet_redispatch_extractor import extract


TENNET_OPERATOR = "TenneT DE"
REDUCTION_DIRECTION = "Wirkleistungseinspeisung reduzieren"
TEST_REASON = "Probefahrt"


#classify Redispatch events as TenneT-related or not
def classify_events(events):
    classified = []

    for event in events:
        requesting_operators = {
            operator.strip()
            for operator in event["requesting_operator"].split("&")
        }

        tennet_requested = TENNET_OPERATOR in requesting_operators
        tennet_instructed = (
            event["instructing_operator"] == TENNET_OPERATOR
        )

        generation_reduction = (
            event["direction"] == REDUCTION_DIRECTION
        )
        test_run = event["reason"] == TEST_REASON

        classified.append({
            **event,
            "tennet_requested": tennet_requested,
            "tennet_instructed": tennet_instructed,
            "tennet_related": tennet_requested or tennet_instructed,
            "generation_reduction": generation_reduction,
            "test_run": test_run,
        })

    return classified


if __name__ == "__main__":
    source = Path("data/raw/Redispatch_Daten.csv")

    events, rejected, duplicates, checksum = extract(source)
    classified = classify_events(events)

    print("Total observations:", len(classified))
    print(
        "TenneT requested:",
        sum(e["tennet_requested"] for e in classified),
    )
    print(
        "TenneT instructed:",
        sum(e["tennet_instructed"] for e in classified),
    )
    print(
        "TenneT related (unique):",
        sum(e["tennet_related"] for e in classified),
    )
    print(
        "TenneT-requested non-test reductions:",
        sum(
            e["tennet_requested"]
            and e["generation_reduction"]
            and not e["test_run"]
            for e in classified
        ),
    )
