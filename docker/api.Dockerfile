# ARVA API and worker image (same image, different command).
# External QC tools come from Debian's signed repositories (multi-architecture:
# amd64 and arm64, so the image also runs on Apple Silicon).
FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARVA_STORAGE_ROOT=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends seqkit fastp filtlong fastqc \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system arva && useradd --system --gid arva --home /opt/arva arva \
    && mkdir -p /data && chown arva:arva /data

WORKDIR /opt/arva
COPY scientific-core ./scientific-core
COPY workflows/tool-adapters ./workflows/tool-adapters
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
# The pod5 extra (official Oxford Nanopore library, MPL-2.0) lets the worker read POD5 run metadata.
RUN pip install ./scientific-core ./workflows/tool-adapters "./apps/api[pod5]"

COPY docker/api-entrypoint.sh /usr/local/bin/arva-api
RUN chmod 755 /usr/local/bin/arva-api

USER arva
WORKDIR /opt/arva/apps/api
EXPOSE 8000
CMD ["arva-api"]
