#!/bin/sh
# Double-click in Finder to stop ARVA (scripts/stop.sh: the containers stop; projects and databases are kept).
cd "$(dirname "$0")" || exit 1
PATH=$PATH:/usr/local/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin
export PATH
sh scripts/stop.sh "$@"
status=$?
printf '\n'
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-$(defaults read -g AppleLocale 2>/dev/null)}}}" in
  es*) printf '%s' "Presionar Enter para cerrar esta ventana. " ;;
  *) printf '%s' "Press Enter to close this window. " ;;
esac
read -r _ || true
exit "$status"
