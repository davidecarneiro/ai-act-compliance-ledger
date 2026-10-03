# Container demonstration: generates fresh evidence, not the published records.
# UUIDs, timestamps and generated keys vary between runs.
# Ed25519 signatures are deterministic for an identical key and message.
FROM python:3.11-slim-bookworm

WORKDIR /sim

# The slim image has no make, and the default command is `make demo`.
RUN apt-get update && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY configs/ ./configs/
COPY tests/ ./tests/
COPY Makefile .

# Non-root user for defence in depth — the simulator never needs root.
RUN useradd --create-home --shell /bin/bash oracle && chown -R oracle:oracle /sim
USER oracle

# Default target runs the full Phase-1+2 pipeline: tests, baseline run,
# comparison vs SQLite baseline, sensitivity sweep, OSCAL export.
CMD ["make", "demo"]
