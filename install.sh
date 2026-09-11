#!/usr/bin/env bash
# Install youtube-scout as the /scout skill. Copy-based, never symlinked.
#
#   ./install.sh                     # Claude Code: ~/.claude/skills/scout
#   ./install.sh --target codex      # ~/.codex/skills/scout
#   ./install.sh --target agents     # ~/.agents/skills/scout
#   ./install.sh --target portable   # ~/.agent-skills/scout
#   ./install.sh --target all
#   ./install.sh --path /some/dir    # custom destination
#
# YOUTUBE_SCOUT_INSTALL_HOME overrides $HOME (used by tests).
set -euo pipefail

main() {
  local source_dir
  source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local base_home="${YOUTUBE_SCOUT_INSTALL_HOME:-$HOME}"
  local target="claude"
  local custom_path=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --target) target="$2"; shift 2 ;;
      --path) custom_path="$2"; target="custom"; shift 2 ;;
      -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}"; exit 0 ;;
      *) echo "install.sh: unknown option $1" >&2; exit 1 ;;
    esac
  done

  if [ ! -f "${source_dir}/SKILL.md" ] || [ ! -f "${source_dir}/scripts/scout.py" ]; then
    echo "install.sh: run this from a youtube-scout checkout (SKILL.md and scripts/scout.py missing)" >&2
    exit 1
  fi

  local -a dests=()
  case "$target" in
    claude) dests=("${base_home}/.claude/skills/scout") ;;
    codex) dests=("${base_home}/.codex/skills/scout") ;;
    agents) dests=("${base_home}/.agents/skills/scout") ;;
    portable) dests=("${base_home}/.agent-skills/scout") ;;
    all) dests=("${base_home}/.claude/skills/scout" "${base_home}/.codex/skills/scout"
                "${base_home}/.agents/skills/scout" "${base_home}/.agent-skills/scout") ;;
    custom) dests=("${custom_path}") ;;
    *) echo "install.sh: unknown target ${target}" >&2; exit 1 ;;
  esac

  for dest in "${dests[@]}"; do
    install_one "${source_dir}" "${dest}"
  done

  if ! python3 -c "import openpyxl" >/dev/null 2>&1; then
    echo "note: openpyxl is not installed for python3. Run: python3 -m pip install --user openpyxl"
  fi
  if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "note: yt-dlp not found. --hooks, --download, and --transcribe need it: python3 -m pip install --user yt-dlp"
  fi
}

install_one() {
  local source_dir="$1"
  local dest="$2"
  rm -rf "${dest}"
  mkdir -p "${dest}/scripts"
  for file in SKILL.md README.md LICENSE CHANGELOG.md requirements.txt; do
    if [ -f "${source_dir}/${file}" ]; then
      cp "${source_dir}/${file}" "${dest}/${file}"
    fi
  done
  cp "${source_dir}/scripts/scout.py" "${dest}/scripts/scout.py"
  chmod +x "${dest}/scripts/scout.py"
  chmod -R go-rwx "${dest}"
  echo "installed youtube-scout to ${dest}"
}

main "$@"
