# ARVA API and worker image (same image, different command).
FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARVA_STORAGE_ROOT=/data

RUN groupadd --system arva && useradd --system --gid arva --home /opt/arva arva \
    && mkdir -p /data && chown arva:arva /data

WORKDIR /opt/arva
COPY scientific-core ./scientific-core
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN pip install ./scientific-core ./apps/api

COPY docker/api-entrypoint.sh /usr/local/bin/arva-api
RUN chmod 755 /usr/local/bin/arva-api

USER arva
WORKDIR /opt/arva/apps/api
EXPOSE 8000
CMD ["arva-api"]
