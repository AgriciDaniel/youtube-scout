# Agent notes for youtube-scout

Portable instructions for any coding agent (Codex, Gemini, Cursor, and others) working in this
repository. Claude Code reads `CLAUDE.md`, which says the same thing.

## What this is

A single-script Claude Code skill. `scripts/scout.py` searches YouTube Data API v3 for a topic,
enriches each video, and writes an `.xlsx` research workbook. `SKILL.md` is the runtime contract
the agent follows when a user types `/scout`.

## Rules

1. Keep dependencies to the standard library plus openpyxl. yt-dlp is optional.
2. Run `python -m pytest` and `ruff check .` before proposing a change. Tests are offline.
3. Never commit keys, `.env` files, workbooks, downloads, or cache. The hygiene test enforces it.
4. No em dashes in any output.
5. Update `SKILL.md`, `README.md`, and `CHANGELOG.md` when flags, columns, or exit codes change.
6. Do not change repository visibility, create releases, or push without explicit instruction.
