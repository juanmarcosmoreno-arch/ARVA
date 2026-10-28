# ARVA API and worker image (same image, different command).
# External QC tools come from Debian's signed repositories (multi-architecture:
# amd64 and arm64, so the image also runs on Apple Silicon).
FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARVA_STORAGE_ROOT=/data \
    ARVA_DB_DIR=/databases

# Flye calls flye-samtools; when the flye package lacks it (Ubuntu's 2.9.3 does), ARVA links it to samtools per run.
# minimap2 is the aligner QUAST uses with a reference (bookworm: 2.24, the version QUAST 5.2.0 bundles).
# SPAdes 3.15.5 and Unicycler 0.5.0 (bookworm's versions, validated with ARVA); Unicycler calls SPAdes, Racon (long
# reads) and makeblastdb/tblastn from ncbi-blast+ (rotating circular replicons). Both run on Debian's own
# /usr/bin/python3 (absolute shebangs), not the image's Python. Debian's unicycler package also depends on pilon
# (and so a Java runtime), bowtie2 and bcftools, which Unicycler 0.5.0 no longer calls.
# Polishing: Racon (with minimap2) for long reads; Pilon 1.24 with BWA and samtools for short reads, run by ARVA as
# `java -Xmx<heap> -jar /usr/share/java/pilon.jar` (Debian's launcher fixes a 16 GB heap), hence the explicit Java
# runtime; MUMmer 3.23 (nucmer, dnadiff) compares draft and polished sequence. Debian's Pilon prints no version
# number, so ARVA reads it from dpkg.
# Annotation: the programs Bakta's steps call, and Prokka. Validated with ARVA on Ubuntu 24.04 only (tRNAscan-SE
# 2.0.12, Aragorn 1.2.41, Infernal 1.1.5, DIAMOND 2.1.9, HMMER 3.4, PILER-CR 1.06, Prokka 1.14.6+dfsg-6). Bookworm
# ships older ones, and ARVA's start-up checks (Bakta's own minimums) then skip the steps that need them, saying so
# in each run: tRNAscan-SE 2.0.10 (< 2.0.12: tRNA), Aragorn 1.2.38 (< 1.2.41: tmRNA), Infernal 1.1.4 (< 1.1.5: rRNA
# and ncRNA), DIAMOND 2.1.3 and no AMRFinderPlus package (CDS, sORF), BLAST+ 2.12.0 (< 2.17.0: oriC/oriV/oriT).
# Bookworm's prokka 1.14.6+dfsg-4 lacks the kingdom protein sets, so ARVA reports Prokka as unable to annotate.
# trnascan-se, infernal, hmmer (so barrnap) and prokka are amd64-only in bookworm.
RUN set -eu; extra=""; \
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then extra="trnascan-se infernal hmmer barrnap prokka"; fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends seqkit fastp filtlong fastqc flye samtools minimap2 \
       spades unicycler racon ncbi-blast+ pilon bwa mummer default-jre-headless \
       aragorn pilercr diamond-aligner prodigal $extra \
    && rm -rf /var/lib/apt/lists/*

# Python report tools, each in its own virtual environment with the versions validated with ARVA.
# Build with --build-arg ARVA_PYTHON_TOOLS="" for a smaller image without them (MultiQC and NanoPlot take about
# 1.7 GB; QUAST about 0.15 GB, measured as an installed venv outside Docker).
# QUAST 5.2.0 is a source package: it imports distutils (setuptools provides it on Python 3.12) and is built with
# that pinned setuptools; its optional parts (gene finding, BUSCO, read analysis) are neither built nor downloaded.
# Bakta 1.12.2 with its direct requirements at the versions validated with ARVA (about 0.32 GB as a venv); its
# database is not part of the image: install it from the Database Manager into ARVA_DB_DIR (/databases).
ARG ARVA_PYTHON_TOOLS="multiqc nanoplot quast bakta"
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
        bakta) python -m venv /opt/arva-tools/bakta \
               && /opt/arva-tools/bakta/bin/pip install "bakta==1.12.2" "biopython==1.88" "xopen==2.1.0" \
                  "requests==2.34.2" "alive-progress==3.3.0" "PyYAML==6.0.3" "pyrodigal==3.7.1" "pyhmmer==0.12.3" \
                  "pyCirclize==1.10.1" ;; \
        *) echo "Unknown ARVA_PYTHON_TOOLS entry: $tool" >&2; exit 1 ;; \
      esac; \
    done
ENV ARVA_TOOL_MULTIQC=/opt/arva-tools/multiqc/bin/multiqc \
    ARVA_TOOL_NANOPLOT=/opt/arva-tools/nanoplot/bin/NanoPlot \
    ARVA_TOOL_QUAST=/opt/arva-tools/quast/bin/quast.py \
    ARVA_TOOL_BAKTA=/opt/arva-tools/bakta/bin/bakta

# /databases: reference databases (ARVA_DB_DIR); a new named volume takes this folder's owner.
RUN groupadd --system arva && useradd --system --gid arva --home /opt/arva arva \
    && mkdir -p /data /databases && chown arva:arva /data /databases

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
