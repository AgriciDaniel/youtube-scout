#!/usr/bin/env bash
# Remove the installed /scout skill.
#
#   ./uninstall.sh                   # Claude Code: ~/.claude/skills/scout
#   ./uninstall.sh --target all      # every known location
#   ./uninstall.sh --path /some/dir
#
# YOUTUBE_SCOUT_INSTALL_HOME overrides $HOME. The probe cache in ~/.cache/scout is kept;
# delete it yourself if you want it gone.
set -euo pipefail

main() {
  local base_home="${YOUTUBE_SCOUT_INSTALL_HOME:-$HOME}"
  local target="claude"
  local custom_path=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --target) target="$2"; shift 2 ;;
      --path) custom_path="$2"; target="custom"; shift 2 ;;
      -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 0 ;;
      *) echo "uninstall.sh: unknown option $1" >&2; exit 1 ;;
    esac
  done

  local -a dests=()
  case "$target" in
    claude) dests=("${base_home}/.claude/skills/scout") ;;
    codex) dests=("${base_home}/.codex/skills/scout") ;;
    agents) dests=("${base_home}/.agents/skills/scout") ;;
    portable) dests=("${base_home}/.agent-skills/scout") ;;
    all) dests=("${base_home}/.claude/skills/scout" "${base_home}/.codex/skills/scout"
                "${base_home}/.agents/skills/scout" "${base_home}/.agent-skills/scout") ;;
    custom) dests=("${custom_path}") ;;
    *) echo "uninstall.sh: unknown target ${target}" >&2; exit 1 ;;
  esac

  for dest in "${dests[@]}"; do
    if [ -d "${dest}" ] && [ -f "${dest}/SKILL.md" ]; then
      rm -rf "${dest}"
      echo "removed ${dest}"
    else
      echo "nothing to remove at ${dest}"
    fi
  done
}

main "$@"
