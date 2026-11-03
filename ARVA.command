#!/bin/sh
# Double-click in Finder to start ARVA: Terminal opens and runs scripts/start.sh, which asks its first-run questions
# the first time and opens http://localhost:8080 once ARVA answers. The window stays open to show what happened.
# Docker Desktop's docker command may not be on the PATH a Finder-opened Terminal gets (/usr/local/bin, or ~/.docker/bin
# when installed for this user only), so its usual places are added.
cd "$(dirname "$0")" || exit 1
PATH=$PATH:/usr/local/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin
export PATH
sh scripts/start.sh --open "$@"
status=$?
printf '\n'
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-$(defaults read -g AppleLocale 2>/dev/null)}}}" in
  es*) printf '%s' "Presionar Enter para cerrar esta ventana. " ;;
  *) printf '%s' "Press Enter to close this window. " ;;
esac
read -r _ || true
exit "$status"
