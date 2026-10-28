
# IRIS Task 093 — TenneT Grid Stress Data Pipeline

FROM python:3.12.10-slim-bookworm

# Python runtime configuration
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Application directory
WORKDIR /app

# Install pinned Python dependencies
COPY requirements-tennet.txt ./requirements-tennet.txt

RUN python -m pip install --no-cache-dir \
    -r requirements-tennet.txt

# Create a non-root application user
RUN useradd --create-home --uid 10001 iris

# Copy application source and automated tests
COPY --chown=iris:iris app/ ./app/
COPY --chown=iris:iris tests/ ./tests/

# Run using a non-root user
USER iris

# Safe default: preview only, no database writes
CMD ["python", "-m", "app.loaders.tennet_redispatch_loader"]
