#!/usr/bin/env bash
# Make room on a GitHub-hosted runner for the ARVA API image (about 15 GB unpacked on amd64, held by the builder and
# again by Docker after loading it for the smoke test): remove preinstalled SDKs ARVA's build does not use, and move
# Docker's data to the runner's second disk (/mnt) when that disk has more free space than the root disk.
# Run before anything starts a container: Docker is restarted when its data move.
set -euo pipefail

df -h / /mnt 2>/dev/null || df -h /
for dir in /usr/share/dotnet /usr/local/lib/android /opt/ghc /usr/local/.ghcup /opt/hostedtoolcache/CodeQL \
  /usr/local/share/boost /usr/share/swift /usr/local/julia* /opt/az /usr/local/share/powershell \
  /usr/local/share/chromium /opt/microsoft /opt/google; do
  if [ -e "$dir" ]; then sudo rm -rf "$dir"; fi
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
