#!/usr/bin/env bash
# Smoke test of a freshly built ARVA API image and web image (run by .github/workflows/images.yml, also by hand):
#   1. every tool adapter's detection inside the API image (scripts/ci/check_image_tools.py);
#   2. one small real analysis: mlst on Staphylococcus aureus NCTC 8325 (NCBI RefSeq NC_007795.1, fetched from NCBI
#      E-utilities and checked against its SHA-256; ARVA's mlst tests found saureus ST8 on it,
#      workflows/tool-adapters/tests/fixtures/mlst/README.md) and SeqKit's length of the same file;
#   3. the API against PostgreSQL and Redis: database migrations to the newest revision, GET /health, the worker;
#   4. the web image in front of it: the interface, and /health and /api/v1/tools through its proxy.
# Usage: scripts/ci/smoke-images.sh API_IMAGE WEB_IMAGE EXPECTED_COMMIT OUT_DIR
set -euo pipefail

api_image=$1 web_image=$2 commit=$3 out=$4
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
net=arva-smoke-$$
genome_acc=NC_007795.1
genome_sha=04b865e316d64ee393dcffcf1cc31c7eaa14a38f4a74c04e385d2acb8e819731
genome_len=2821361

cleanup() {
  docker logs smoke-api > "$out/api.log" 2>&1 || true
  docker logs smoke-worker > "$out/worker.log" 2>&1 || true
  docker logs smoke-web > "$out/web.log" 2>&1 || true
  docker rm -f smoke-api smoke-worker smoke-web smoke-postgres smoke-redis > /dev/null 2>&1 || true
  docker network rm "$net" > /dev/null 2>&1 || true
}
trap cleanup EXIT
mkdir -p "$out/in"
chmod 0777 "$out"

wait_for() {
  local what=$1 tries=$2
  shift 2
  for _ in $(seq "$tries"); do
    if "$@" > /dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "Timed out waiting for $what" >&2
  return 1
}

echo "==> Image architecture and commit"
docker image inspect --format '{{.Os}}/{{.Architecture}}' "$api_image" "$web_image"
got=$(docker run --rm "$api_image" printenv ARVA_GIT_COMMIT)
if [ "$got" != "$commit" ]; then
  echo "ARVA_GIT_COMMIT in the API image is '$got', expected '$commit'" >&2
  exit 1
fi

echo "==> Tool detection inside the API image"
docker run --rm -v "$ROOT:/src:ro" -v "$out:/out" "$api_image" \
  python -I /src/scripts/ci/check_image_tools.py --repo /src --json /out/tools.json

echo "==> mlst on $genome_acc (real public genome)"
curl -fsS --retry 5 --retry-delay 10 -o "$out/in/$genome_acc.fasta" \
  "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=$genome_acc&rettype=fasta&retmode=text"
echo "$genome_sha  $out/in/$genome_acc.fasta" | sha256sum -c -
chmod 0755 "$out/in"
chmod 0644 "$out/in/$genome_acc.fasta"
docker run --rm -v "$out/in:/in:ro" -e PATH=/opt/arva-tools/conda/mlst/bin:/usr/local/bin:/usr/bin:/bin "$api_image" \
  mlst --nopath --quiet \
  "/in/$genome_acc.fasta" | tee "$out/mlst.tsv"
awk -F '\t' 'NR == 1 && $2 == "saureus" && $3 == "8" { ok = 1 } END { exit !ok }' "$out/mlst.tsv" || {
  echo "mlst did not report saureus ST8 for $genome_acc" >&2
  exit 1
}
docker run --rm -v "$out/in:/in:ro" "$api_image" seqkit stats -T "/in/$genome_acc.fasta" | tee "$out/seqkit.tsv"
awk -F '\t' -v len="$genome_len" 'NR == 2 && $4 == 1 && $5 == len { ok = 1 } END { exit !ok }' "$out/seqkit.tsv" || {
  echo "seqkit did not report one sequence of $genome_len bp" >&2
  exit 1
}

echo "==> API with PostgreSQL and Redis"
docker network create "$net" > /dev/null
docker run -d --name smoke-postgres --network "$net" -e POSTGRES_USER=arva -e POSTGRES_PASSWORD=smoke \
  -e POSTGRES_DB=arva postgres:16.4-alpine > /dev/null
docker run -d --name smoke-redis --network "$net" redis:7.4.1-alpine redis-server --save '' --appendonly no > /dev/null
wait_for PostgreSQL 60 docker exec smoke-postgres pg_isready -U arva -d arva
env_args=(-e "ARVA_DATABASE_URL=postgresql+psycopg://arva:smoke@smoke-postgres:5432/arva"
  -e "ARVA_REDIS_URL=redis://smoke-redis:6379/0" -e 'ARVA_CORS_ORIGINS=["http://localhost:8080"]')
docker run -d --name smoke-api --network "$net" --network-alias api "${env_args[@]}" "$api_image" > /dev/null
wait_for "API /health" 150 docker exec smoke-api python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
docker exec smoke-api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())" |
  tee "$out/health.json"
grep -q '"version"' "$out/health.json"
docker exec smoke-api alembic current 2>&1 | tee "$out/alembic.txt"
grep -q '(head)' "$out/alembic.txt" || {
  echo "The database is not at the newest migration" >&2
  exit 1
}
docker run -d --name smoke-worker --network "$net" "${env_args[@]}" "$api_image" \
  python /opt/arva/apps/workers/run_worker.py > /dev/null
sleep 15
if [ "$(docker inspect -f '{{.State.Running}}' smoke-worker)" != true ]; then
  echo "The worker stopped" >&2
  exit 1
fi

echo "==> Web image in front of the API"
docker run -d --name smoke-web --network "$net" -p 127.0.0.1:18080:80 "$web_image" > /dev/null
wait_for "web /" 60 curl -fsS -o /dev/null http://127.0.0.1:18080/
curl -fsS http://127.0.0.1:18080/ | grep -q '<div id="root">'
curl -fsS http://127.0.0.1:18080/health | grep -q '"status"'
curl -fsS http://127.0.0.1:18080/api/v1/tools > "$out/tools-api.json"
python3 -c "import json, sys; d = json.load(open(sys.argv[1])); assert isinstance(d, list) and len(d) > 30, len(d)" \
  "$out/tools-api.json"
docker exec smoke-web sh -c "grep -rlF '$commit' /usr/share/nginx/html/assets" > /dev/null || {
  echo "The web build does not contain the commit $commit" >&2
  exit 1
}
echo "Smoke test passed"
