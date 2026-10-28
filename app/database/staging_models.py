
"""Independent SQLAlchemy models for IRIS staging data.

Do not import these models into the existing iris_core registry.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class StagingBase(DeclarativeBase):
    """Separate metadata registry for staging tables."""

    pass


class GridCongestionTimeSeries(StagingBase):
    """Normalized source-backed grid redispatch observations."""

    __tablename__ = "grid_congestion_timeseries"

    __table_args__ = (
        CheckConstraint(
            "end_utc > start_utc",
            name="ck_grid_congestion_valid_interval",
        ),
        CheckConstraint(
            "average_power_mw >= 0",
            name="ck_grid_congestion_average_power",
        ),
        CheckConstraint(
            "maximum_power_mw >= 0",
            name="ck_grid_congestion_maximum_power",
        ),
        Index(
            "idx_grid_congestion_start_utc",
            "start_utc",
        ),
        {
            "schema": "iris_staging",
        },
    )

    # Source identity and provenance

    record_sha256: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    source_file_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Observation timestamps

    start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Operators and affected facilities

    requesting_operator: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    instructing_operator: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    affected_facility: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    primary_energy_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Redispatch measurements

    direction: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    average_power_mw: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    maximum_power_mw: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    total_energy_mwh: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    # TenneT classification

    tennet_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    tennet_instructed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    tennet_related: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    generation_reduction: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    test_run: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    # Fields not established by the current source

    bottleneck_location: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    curtailed_mw: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    # Ingestion audit timestamp

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
