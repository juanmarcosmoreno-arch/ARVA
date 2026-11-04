#!/usr/bin/env bash
# Make room on a GitHub-hosted runner for the ARVA API image (about 15 GB unpacked on amd64, held by the builder and
# again by Docker after loading it for the smoke test): remove preinstalled SDKs ARVA's build does not use, and move
# Docker's data to the runner's second disk (/mnt) when that disk has more free space than the root disk.
# Run before anything starts a container: Docker is restarted when its data move.
set -euo pipefail

df -h / /mnt 2>/dev/null || df -h /
# The build needs about 45 GB on amd64 (the 18 GB image loaded into Docker plus the builder's layers, measured on the
# runs of 2026-11-03); some runners have a 72 GB root disk with about 46 GB free after the first list, which was not
# enough, so the second list (tool caches and SDKs the image build and smoke test never use: the workflow uses no
# setup-* action, and the smoke test runs the system python3) and the swap file go too.
for dir in /usr/share/dotnet /usr/local/lib/android /opt/ghc /usr/local/.ghcup /opt/hostedtoolcache/CodeQL \
  /usr/local/share/boost /usr/share/swift /usr/local/julia* /opt/az /usr/local/share/powershell \
  /usr/local/share/chromium /opt/microsoft /opt/google \
  /opt/hostedtoolcache /usr/lib/jvm /usr/local/lib/node_modules /usr/share/miniconda /usr/local/share/vcpkg \
  /opt/pipx /usr/lib/google-cloud-sdk /usr/local/aws-cli /usr/local/aws-sam-cli /opt/mssql-tools /usr/lib/firefox \
  /usr/local/share/gradle* /usr/share/kotlinc /usr/local/go /opt/actionarchivecache; do
  if [ -e "$dir" ]; then sudo rm -rf "$dir"; fi
done
for swap in /swapfile /mnt/swapfile; do
  if [ -f "$swap" ]; then sudo swapoff "$swap" 2>/dev/null || true; sudo rm -f "$swap"; fi
done
docker system prune -af > /dev/null || true

root_free=$(df -Pk / | awk 'NR == 2 { print $4 }')
mnt_free=$(df -Pk /mnt 2>/dev/null | awk 'NR == 2 { print $4 }' || true)
if [ -n "$mnt_free" ] && [ "$mnt_free" -gt "$root_free" ] && [ "$(df -P /mnt | awk 'NR == 2 { print $6 }')" = /mnt ]; then
  echo "Moving Docker's data to /mnt/docker ($((mnt_free / 1048576)) GB free there, $((root_free / 1048576)) GB on /)"
  sudo systemctl stop docker.socket docker.service
  sudo mkdir -p /mnt/docker
  conf=/etc/docker/daemon.json
  current='{}'
  if [ -s "$conf" ]; then current=$(sudo cat "$conf"); fi
  printf '%s' "$current" | jq '. + {"data-root": "/mnt/docker"}' | sudo tee "$conf.new" > /dev/null
  sudo mv "$conf.new" "$conf"
  sudo systemctl start docker.service
  docker info --format 'Docker data root: {{.DockerRootDir}}'
fi
df -h / /mnt 2>/dev/null || df -h /
