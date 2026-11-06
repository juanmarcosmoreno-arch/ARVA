#!/usr/bin/env bash
# Install micromamba, the static conda package manager, from its official conda-forge package. ARVA uses it only
# to create the Bioconda tool environments from the checked-in lock files (docker/conda-locks, see
# docs/installation.md); it never solves or updates an environment at run time.
#
# The package's SHA-256 is pinned below per platform. Each value was compared, when pinned, with the sha256 that
# conda-forge's repodata.json lists for the file (scripts/conda_locks.py verify-micromamba repeats the check).
#
# Usage: scripts/install-micromamba.sh [PREFIX]   (default: ~/.arva-tools/micromamba; installs PREFIX/bin/micromamba)
set -euo pipefail

VERSION="2.9.0"
BUILD="0"
PREFIX="${1:-${ARVA_MICROMAMBA_PREFIX:-$HOME/.arva-tools/micromamba}}"

# Linux: the Bioconda tools of ARVA's image and of a Linux installation. macOS on Apple silicon (osx-arm64): only for
# the optional native Flye and Bakta that ARVA.app runs (docs/plan-flye-nativo.md); every other tool runs in Docker.
case "$(uname -s)" in
  Linux)
    case "$(uname -m)" in
      x86_64 | amd64) SUBDIR="linux-64"; SHA256="8761c382127e6363bd9e0a2451aa3ef90d071a79133f736e2f759a3bf13040dd" ;;
      aarch64 | arm64) SUBDIR="linux-aarch64"; SHA256="e705ffeed90ce0659eb546e4b1e1028c9eaf0bc9cc854867b19ac5ce0ba5852f" ;;
      *) echo "No pinned micromamba package for $(uname -m)." >&2; exit 1 ;;
    esac ;;
  Darwin)
    case "$(uname -m)" in
      arm64) SUBDIR="osx-arm64"; SHA256="500f5074feb8d02c4296ef9921c3650ed2874171805a9fbb8fbb53896433646b" ;;
      *) echo "ARVA's native tools (Flye, Bakta) are for Apple silicon (arm64) only; this Mac is $(uname -m)." >&2; exit 1 ;;
    esac ;;
  *)
    echo "ARVA runs its Bioconda tools on Linux (on a Mac, inside the Docker image)." >&2
    exit 1 ;;
esac
# macOS has shasum (Perl) rather than GNU sha256sum; both read "<sha256>  <file>" lines with -c.
if command -v sha256sum >/dev/null 2>&1; then
  SHA_CHECK=(sha256sum -c --quiet -)
else
  SHA_CHECK=(shasum -a 256 -c --quiet -)
fi

FILE="micromamba-${VERSION}-${BUILD}.tar.bz2"
URL="https://conda.anaconda.org/conda-forge/${SUBDIR}/${FILE}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Downloading ${URL}"
curl -fsSL --retry 3 -o "$WORK/$FILE" "$URL"
echo "${SHA256}  $WORK/$FILE" | "${SHA_CHECK[@]}" || {
  echo "The package's SHA-256 does not match the pinned value; nothing was installed." >&2
  exit 1
}
mkdir -p "$WORK/pkg"
tar -xjf "$WORK/$FILE" -C "$WORK/pkg"
install -d "$PREFIX/bin" "$PREFIX/licenses"
install -m 0755 "$WORK/pkg/bin/micromamba" "$PREFIX/bin/micromamba"
if [ -d "$WORK/pkg/info/licenses" ]; then
  cp -R "$WORK/pkg/info/licenses/." "$PREFIX/licenses/"
fi
printf '%s\n' "micromamba ${VERSION} build ${BUILD} (${SUBDIR}) sha256 ${SHA256}" "source ${URL}" > "$PREFIX/SOURCE"
echo "==> Installed $("$PREFIX/bin/micromamba" --version) at $PREFIX/bin/micromamba"
