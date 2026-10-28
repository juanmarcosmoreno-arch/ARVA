# ARVA API and worker image (same image, different command).
# External QC tools come from Debian's signed repositories (multi-architecture:
# amd64 and arm64, so the image also runs on Apple Silicon).
FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARVA_STORAGE_ROOT=/data

# Flye calls flye-samtools; when the flye package lacks it (Ubuntu's 2.9.3 does), ARVA links it to samtools per run.
# minimap2 is the aligner QUAST uses with a reference (bookworm: 2.24, the version QUAST 5.2.0 bundles).
RUN apt-get update \
    && apt-get install -y --no-install-recommends seqkit fastp filtlong fastqc flye samtools minimap2 \
    && rm -rf /var/lib/apt/lists/*

# Python report tools, each in its own virtual environment with the versions validated with ARVA.
# Build with --build-arg ARVA_PYTHON_TOOLS="" for a smaller image without them (MultiQC and NanoPlot take about
# 1.7 GB; QUAST about 0.15 GB, measured as an installed venv outside Docker).
# QUAST 5.2.0 is a source package: it imports distutils (setuptools provides it on Python 3.12) and is built with
# that pinned setuptools; its optional parts (gene finding, BUSCO, read analysis) are neither built nor downloaded.
ARG ARVA_PYTHON_TOOLS="multiqc nanoplot quast"
RUN set -eu; for tool in $ARVA_PYTHON_TOOLS; do \
      case "$tool" in \
        multiqc) python -m venv /opt/arva-tools/multiqc \
                 && /opt/arva-tools/multiqc/bin/pip install "multiqc==1.35" "plotly==5.24.1" ;; \
        nanoplot) python -m venv /opt/arva-tools/nanoplot \
                  && /opt/arva-tools/nanoplot/bin/pip install "NanoPlot==1.48.0" "nanoget==1.19.6" ;; \
        quast) python -m venv /opt/arva-tools/quast \
               && /opt/arva-tools/quast/bin/pip install "setuptools==80.9.0" \
               && /opt/arva-tools/quast/bin/pip install --no-build-isolation "quast==5.2.0" "joblib==1.5.2" \
                  "simplejson==3.20.2" ;; \
        *) echo "Unknown ARVA_PYTHON_TOOLS entry: $tool" >&2; exit 1 ;; \
      esac; \
    done
ENV ARVA_TOOL_MULTIQC=/opt/arva-tools/multiqc/bin/multiqc \
    ARVA_TOOL_NANOPLOT=/opt/arva-tools/nanoplot/bin/NanoPlot \
    ARVA_TOOL_QUAST=/opt/arva-tools/quast/bin/quast.py

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
