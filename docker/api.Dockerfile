# ARVA API and worker image (same image, different command).
# External tools come from Debian's signed repositories and from Bioconda locks; the image builds for amd64 and arm64,
# and some tools exist for amd64 only (below; docs/installation.md, Apple silicon).

FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARVA_STORAGE_ROOT=/data \
    ARVA_DB_DIR=/databases

# Bioconda tools: micromamba (conda-forge's package, SHA-256 pinned in scripts/install-micromamba.sh) creates one
# environment per tool from the checked-in lock of the image's architecture (docker/conda-locks/<tool>/
# linux-64.lock or linux-aarch64.lock: exact package URLs with their SHA-256; micromamba refuses any other file).
# micromamba, its package cache and the build inputs exist only during this RUN (bind mounts and a temporary folder),
# so the layer holds the environments alone, once: a stage of its own would store them twice in the build cache.
# Only the two scripts it runs are mounted, so that a change to another script does not rebuild this layer.
# mlst 2.35.0 with BLAST+ 2.16.0 has locks for both architectures (about 0.95 GB installed, measured on linux-64);
# so have FastANI 1.34 (95 MB), skani 0.4.0 (31 MB), Mash 2.3 (135 MB) and sylph 1.0.0 (30 MB), the species
# identification tools, and AMRFinderPlus 4.2.7 with BLAST+ 2.16.0 and HMMER 3.4 (0.87 GB). Bakta 1.12.2 with every
# program it runs (tRNAscan-SE 2.0.13, Aragorn 1.2.41, Infernal 1.1.5, PILER-CR 1.06, Pyrodigal 3.7.1, AMRFinderPlus
# 4.2.7, PyHMMER 0.12.3, DIAMOND 2.2.8, BLAST+ 2.17.0, pyCirclize 1.10.1; 1.43 GB) has a linux-64 lock only: Bioconda
# has no BLAST+ 2.17.0, which Bakta's recipe requires, for linux-aarch64 (docker/conda-locks/bakta/
# linux-aarch64.unavailable); arm64 images get the PyPI Bakta below instead. GTDB-Tk 2.8.0 has a linux-64 lock only
# (about 0.43 GB; its reference data, about 100 GB, are registered separately) and is not built by default: add
# "gtdbtk" to ARVA_CONDA_TOOLS on amd64 to include it. ABRicate 1.4.0 (with its VFDB and PlasmidFinder copies, BLAST+
# 2.16.0; about 1.3 GB) has locks for both architectures; MOB-suite 3.1.9 (BLAST+ 2.15.0, its recipe needs < 2.16;
# about 2.2 GB) and IntegronFinder 2.0.6 (HMMER 3.3.2, Infernal, Prodigal; about 0.7 GB) for linux-64 only (Bioconda
# has no BLAST+ < 2.16 or HMMER <= 3.3.2 for linux-aarch64). MOB-suite's post-link script, which runs mob_init (a
# download with TLS verification off), is not run: scripts/conda_locks.py passes --skip-run-link-scripts. ISEScan
# 1.7.3 (linux-64; validated with a real run, about 1.4 GB unpacked) and geNomad 1.13.0 (both architectures; not
# validated) are not built by default: add "isescan" or "genomad" to ARVA_CONDA_TOOLS to include them. S. aureus typing: sccmec
# 1.2.0 (camlhmp 1.1.4, BLAST+ 2.16.0; about 1.0 GB) and spaTyper 0.3.3 (about 0.17 GB) have locks for both
# architectures; AgrVATE 1.0.2 (snippy 4.6.0, MUMmer 3.23, HMMER, BLAST+; about 2.6 GB) for linux-64 only (snippy's
# dependencies cannot be solved for linux-aarch64). spaTyper's package bundles copies of the Ridom SpaServer files,
# which conda_locks.py deletes after installing (docker/conda-locks/spatyper/remove-after-install.txt): ARVA never
# ships them. Long-read filtering and assembly: Filtlong 0.3.1 (29 MB) and Flye 2.9.6 (with its own Python 3.13 and
# its programs flye-modules, flye-minimap2 and flye-samtools; 280 MB, measured on linux-64) have locks for both
# architectures; they replace Debian's filtlong 0.2.1 and flye 2.9.1, which are no longer installed (ARVA_TOOL_FLYE
# and ARVA_TOOL_FILTLONG point at the environments, and ARVA does not fall back to PATH when an ARVA_TOOL_<ID> file
# is missing). Medaka 2.1.1 (Nanopore polishing; PyTorch 2.3.1 CPU build, its own minimap2 2.31, samtools 1.24 and
# bcftools 1.25; 1.63 GB unpacked, measured on linux-64) has locks for both architectures; its package ships the
# consensus models r1041_e82_400bps_sup_v5.2.0 and r1041_e82_400bps_hac_v5.2.0 (files whose sha256 conda records),
# the only ones ARVA lets it use: other models medaka would download on first use from GitHub without a checksum.
# A tool without a lock for the image's architecture is left out.
# Build with --build-arg ARVA_CONDA_TOOLS="" for an image without them.
ARG ARVA_CONDA_TOOLS="filtlong flye medaka mlst fastani skani mash sylph amrfinderplus bakta abricate mobsuite integronfinder sccmec spatyper agrvate iqtree panaroo"
RUN --mount=type=bind,source=scripts/install-micromamba.sh,target=/build/scripts/install-micromamba.sh \
    --mount=type=bind,source=scripts/conda_locks.py,target=/build/scripts/conda_locks.py \
    --mount=type=bind,source=docker/conda-locks,target=/build/docker/conda-locks \
    set -eu; mkdir -p /opt/arva-tools/conda; \
    plat=linux-64; if [ "$(uname -m)" = "aarch64" ]; then plat=linux-aarch64; fi; \
    if [ -n "$ARVA_CONDA_TOOLS" ]; then \
      apt-get update && apt-get install -y --no-install-recommends ca-certificates curl bzip2 \
        && rm -rf /var/lib/apt/lists/*; \
      mm=$(mktemp -d); /build/scripts/install-micromamba.sh "$mm"; \
      for tool in $ARVA_CONDA_TOOLS; do \
        if [ ! -f "/build/docker/conda-locks/$tool/$plat.lock" ]; then \
          echo "No $plat lock for $tool (docker/conda-locks/$tool/$plat.unavailable); left out"; continue; \
        fi; \
        python3 -I /build/scripts/conda_locks.py --micromamba "$mm/bin/micromamba" install "$tool" \
          "/opt/arva-tools/conda/$tool"; \
      done; \
      rm -rf "$mm"; \
    fi

# Flye (from its Bioconda environment above) ships flye-samtools; samtools below is for polishing, mapping and
# variant calling. A Flye without flye-samtools (Debian's and Ubuntu's packages) gets it linked to samtools per run.
# minimap2 is the aligner QUAST uses with a reference (bookworm: 2.24, the version QUAST 5.2.0 bundles).
# SPAdes 3.15.5 and Unicycler 0.5.0 (bookworm's versions, validated with ARVA); Unicycler calls SPAdes, Racon (long
# reads) and makeblastdb/tblastn from ncbi-blast+ (rotating circular replicons). Both run on Debian's own
# /usr/bin/python3 (absolute shebangs), not the image's Python. Debian's unicycler package also depends on pilon
# (and so a Java runtime), bowtie2 and bcftools, which Unicycler 0.5.0 no longer calls.
# Polishing: Racon (with minimap2) for long reads; Pilon 1.24 with BWA and samtools for short reads, run by ARVA as
# `java -Xmx<heap> -jar /usr/share/java/pilon.jar` (Debian's launcher fixes a 16 GB heap), hence the explicit Java
# runtime; MUMmer 3.23 (nucmer, dnadiff) compares draft and polished sequence. Debian's Pilon prints no version
# number, so ARVA reads it from dpkg.
# Annotation: Prokka and the programs it calls (Debian's), which are also what the PyPI Bakta of arm64 images runs:
# there Bookworm's older versions fail Bakta's own minimums and ARVA's start-up checks skip the steps that need them,
# saying so in each run: tRNAscan-SE (not installed: tRNA), Aragorn 1.2.38 (< 1.2.41: tmRNA), Infernal 1.1.4
# (< 1.1.5: rRNA and ncRNA), DIAMOND 2.1.3 and no AMRFinderPlus package (CDS, sORF), BLAST+ 2.12.0 (< 2.17.0:
# oriC/oriV/oriT). On amd64 Bakta comes from its conda environment with all of its programs (CDS validated there).
# Bookworm's prokka 1.14.6+dfsg-4 lacks the kingdom protein sets, so ARVA reports Prokka as unable to annotate.
# infernal, hmmer (so barrnap), prokka, spades and unicycler are amd64-only in bookworm (Debian's package lists,
# checked with qa.debian.org/madison.php): arm64 images have no SPAdes, Unicycler or Prokka. Debian's trnascan-se is
# in non-free, which the image does not enable; Prokka does not depend on it, and Bakta on amd64 has its own
# tRNAscan-SE 2.0.13 in its conda environment.
# Variant calling: bcftools (mpileup, call, norm, filter, csq) with BWA or minimap2 and samtools; ARVA validated
# bcftools 1.19 (Ubuntu); bookworm ships 1.16, which ARVA runs after checking every option in its usage texts.
RUN set -eu; extra=""; \
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then extra="infernal hmmer barrnap prokka spades unicycler"; fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends seqkit fastp fastqc samtools minimap2 \
       racon ncbi-blast+ pilon bwa mummer default-jre-headless \
       aragorn pilercr diamond-aligner prodigal mafft fasttree snp-sites bcftools $extra \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Python report tools, each in its own virtual environment with the versions validated with ARVA.
# Build with --build-arg ARVA_PYTHON_TOOLS="" for a smaller image without them (MultiQC and NanoPlot take about
# 1.7 GB; QUAST about 0.15 GB, measured as an installed venv outside Docker).
# QUAST 5.2.0 is a source package: it imports distutils (setuptools provides it on Python 3.12) and is built with
# that pinned setuptools; its optional parts (gene finding, BUSCO, read analysis) are neither built nor downloaded.
# Bakta 1.12.2 from PyPI with its direct requirements (about 0.32 GB as a venv) only when there is no conda
# Bakta environment for this architecture (arm64). isal (xopen's compression library) is pinned to 1.8.0, which has
# linux-aarch64 wheels: 1.9.0 (2026-11-02) came without them, and building it needs make and nasm. Its database is not part of the image: install it from the
# Database Manager into ARVA_DB_DIR (/databases), like the AMRFinderPlus database release its CDS step reads.
# The environments stay at the prefix they were created with (/opt/arva-tools/conda/<tool>): conda writes it into
# scripts and libraries, so they cannot be moved. mlst's PubMLST schemes are inside its environment
# (db/), read in place; ARVA lists them as a bundled, read-only database.
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
        bakta) if [ -x /opt/arva-tools/conda/bakta/bin/bakta ]; then continue; fi; \
               python -m venv /opt/arva-tools/bakta \
               && /opt/arva-tools/bakta/bin/pip install "bakta==1.12.2" "biopython==1.88" "xopen==2.1.0" \
                  "requests==2.34.2" "alive-progress==3.3.0" "PyYAML==6.0.3" "pyrodigal==3.7.1" "pyhmmer==0.12.3" \
                  "pyCirclize==1.10.1" "isal==1.8.0" ;; \
        *) echo "Unknown ARVA_PYTHON_TOOLS entry: $tool" >&2; exit 1 ;; \
      esac; \
    done; \
    mkdir -p /opt/arva-tools/bin; \
    for exe in /opt/arva-tools/conda/bakta/bin/bakta /opt/arva-tools/bakta/bin/bakta; do \
      if [ -x "$exe" ]; then ln -s "$exe" /opt/arva-tools/bin/bakta; break; fi; \
    done
# ARVA_TOOL_BAKTA is a link to the Bakta of this image; ARVA follows it to the environment whose programs Bakta runs.
ENV ARVA_TOOL_MULTIQC=/opt/arva-tools/multiqc/bin/multiqc \
    ARVA_TOOL_NANOPLOT=/opt/arva-tools/nanoplot/bin/NanoPlot \
    ARVA_TOOL_QUAST=/opt/arva-tools/quast/bin/quast.py \
    ARVA_TOOL_BAKTA=/opt/arva-tools/bin/bakta
ENV ARVA_TOOL_FILTLONG=/opt/arva-tools/conda/filtlong/bin/filtlong \
    ARVA_TOOL_FLYE=/opt/arva-tools/conda/flye/bin/flye \
    ARVA_TOOL_MEDAKA=/opt/arva-tools/conda/medaka/bin/medaka \
    ARVA_TOOL_AMRFINDERPLUS=/opt/arva-tools/conda/amrfinderplus/bin/amrfinder \
    ARVA_TOOL_MLST=/opt/arva-tools/conda/mlst/bin/mlst \
    ARVA_TOOL_FASTANI=/opt/arva-tools/conda/fastani/bin/fastANI \
    ARVA_TOOL_SKANI=/opt/arva-tools/conda/skani/bin/skani \
    ARVA_TOOL_MASH=/opt/arva-tools/conda/mash/bin/mash \
    ARVA_TOOL_SYLPH=/opt/arva-tools/conda/sylph/bin/sylph \
    ARVA_TOOL_GTDBTK=/opt/arva-tools/conda/gtdbtk/bin/gtdbtk \
    ARVA_TOOL_ABRICATE=/opt/arva-tools/conda/abricate/bin/abricate \
    ARVA_TOOL_MOBSUITE=/opt/arva-tools/conda/mobsuite/bin/mob_recon \
    ARVA_TOOL_INTEGRONFINDER=/opt/arva-tools/conda/integronfinder/bin/integron_finder \
    ARVA_TOOL_ISESCAN=/opt/arva-tools/conda/isescan/bin/isescan.py \
    ARVA_TOOL_GENOMAD=/opt/arva-tools/conda/genomad/bin/genomad \
    ARVA_TOOL_SCCMEC=/opt/arva-tools/conda/sccmec/bin/sccmec \
    ARVA_TOOL_SPATYPER=/opt/arva-tools/conda/spatyper/bin/spaTyper \
    ARVA_TOOL_AGRVATE=/opt/arva-tools/conda/agrvate/bin/agrvate \
    ARVA_TOOL_IQTREE=/opt/arva-tools/conda/iqtree/bin/iqtree3 \
    ARVA_TOOL_PANAROO=/opt/arva-tools/conda/panaroo/bin/panaroo

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

# The git commit the image is built from, in every error log entry and diagnostic report (scripts/start.sh passes
# it; "unknown" otherwise). Last, so that a new commit rebuilds only this layer.
ARG ARVA_GIT_COMMIT=unknown
ENV ARVA_GIT_COMMIT=$ARVA_GIT_COMMIT

USER arva
WORKDIR /opt/arva/apps/api
EXPOSE 8000
CMD ["arva-api"]
