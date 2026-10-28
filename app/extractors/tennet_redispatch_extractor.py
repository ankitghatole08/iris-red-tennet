
"""Read official Redispatch CSV observations from TenneT DE and convert them to a standard format."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SOURCE_URL = "https://www.netztransparenz.de/en/Ancillary-Services/System-operations/Redispatch"

REQUIRED_COLUMNS = (
    "BEGINN_DATUM", "BEGINN_UHRZEIT", "ZEITZONE_VON",
    "ENDE_DATUM", "ENDE_UHRZEIT", "ZEITZONE_BIS",
    "GRUND_DER_MASSNAHME", "RICHTUNG", "MITTLERE_LEISTUNG_MW",
    "MAXIMALE_LEISTUNG_MW", "GESAMTE_ARBEIT_MWH",
    "ANWEISENDER_UENB", "ANFORDERNDER_UENB",
    "BETROFFENE_ANLAGE", "PRIMAERENERGIEART",
)

DIRECTIONS = {
    "Wirkleistungseinspeisung reduzieren",
    "Wirkleistungseinspeisung erhöhen",
}


#parse utc timestamp from date, time and timezone strings
def parse_utc(date_text: str, time_text: str, tz_text: str) -> str:
    if tz_text != "UTC":
        raise ValueError(f"Unsupported timezone: {tz_text!r}")

    value = datetime.strptime(
        f"{date_text} {time_text}", "%d.%m.%Y %H:%M"
    )
    return value.replace(tzinfo=timezone.utc).isoformat()


#parse nonnegative decimal from string, replacing comma with dot
def parse_nonnegative_decimal(value: str) -> str:
    try:
        number = Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc

    if not number.is_finite() or number < 0:
        raise ValueError(f"Invalid nonnegative value: {value!r}")

    return str(number)


#extract Redispatch events from a CSV file
def extract(path: Path):

    #compute SHA-256 hash of the source file for provenance
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()


    events, rejected, duplicates = [], [], 0
    seen = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")

        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Missing required CSV columns: {sorted(missing)}"
            )

        for line_number, row in enumerate(reader, start=2):
            try:
                if None in row or any(
                    row[name] is None or not row[name].strip()
                    for name in REQUIRED_COLUMNS
                ):
                    raise ValueError("Incomplete or malformed CSV record")

                start = parse_utc(
                    row["BEGINN_DATUM"],
                    row["BEGINN_UHRZEIT"],
                    row["ZEITZONE_VON"],
                )
                end = parse_utc(
                    row["ENDE_DATUM"],
                    row["ENDE_UHRZEIT"],
                    row["ZEITZONE_BIS"],
                )

                if end <= start:
                    raise ValueError(
                        "End timestamp must be after start timestamp"
                    )

                if row["RICHTUNG"] not in DIRECTIONS:
                    raise ValueError(
                        f"Unknown adjustment direction: {row['RICHTUNG']!r}"
                    )

                average_mw = parse_nonnegative_decimal(
                    row["MITTLERE_LEISTUNG_MW"]
                )
                maximum_mw = parse_nonnegative_decimal(
                    row["MAXIMALE_LEISTUNG_MW"]
                )
                energy_mwh = parse_nonnegative_decimal(
                    row["GESAMTE_ARBEIT_MWH"]
                )

                #compute SHA-256 hash of the record for deduplication
                record_sha256 = hashlib.sha256(
                    json.dumps(
                        row, sort_keys=True, ensure_ascii=False
                    ).encode("utf-8")
                ).hexdigest()

                if record_sha256 in seen:
                    duplicates += 1
                    continue

                seen.add(record_sha256)

                events.append({
                    "record_sha256": record_sha256,
                    "source_file_sha256": source_sha256,
                    "source_url": SOURCE_URL,
                    "start_utc": start,
                    "end_utc": end,
                    "instructing_operator": row["ANWEISENDER_UENB"],
                    "requesting_operator": row["ANFORDERNDER_UENB"],
                    "affected_facility": row["BETROFFENE_ANLAGE"],
                    "reason": row["GRUND_DER_MASSNAHME"],
                    "direction": row["RICHTUNG"],
                    "average_power_mw": average_mw,
                    "maximum_power_mw": maximum_mw,
                    "total_energy_mwh": energy_mwh,
                    "primary_energy_type": row["PRIMAERENERGIEART"],
                })

            except ValueError as exc:
                rejected.append({
                    "line": line_number,
                    "error": str(exc),
                })

    return events, rejected, duplicates, source_sha256



if __name__ == "__main__":
    source = Path("data/raw/Redispatch_Daten.csv")

    events, rejected, duplicates, checksum = extract(source)

    print(f"Source file: {source}")
    print(f"SHA-256: {checksum}")
    print(f"Valid unique rows: {len(events)}")
    print(f"Duplicate rows: {duplicates}")
    print(f"Rejected rows: {len(rejected)}")
    print(
        "TenneT DE instructed rows:",
        sum(
            event["instructing_operator"] == "TenneT DE"
            for event in events
        ),
    )

    if rejected:
        print("Rejected samples:", rejected[:3])
