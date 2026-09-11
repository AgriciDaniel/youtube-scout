# youtube-scout

Claude Code skill: `/scout <topic>` turns one topic into a ranked YouTube research workbook.
Read `SKILL.md` for the runtime contract and `README.md` for the product view.

## Working in this repo

- Source of truth is this checkout. `~/.claude/skills/scout/` is an installed copy; after
  changing `scripts/scout.py` or `SKILL.md`, run `./install.sh` to refresh it.
- Quality gate: `python -m pytest` (offline, fixtures under `tests/fixtures/`) and
  `ruff check .`. Every behaviour change ships with a test.
- Never commit API keys, `.env` files, generated workbooks, downloads, or the probe cache.
  `tests/test_repo_hygiene.py` fails on em dashes, local absolute paths, key file references,
  credential-shaped strings, and tracked workbooks. Keep it that way.
- No em dashes anywhere: code, comments, docs, commits.
- Commit messages: imperative sentence case, `git commit -s`. No `git add -A`; add files by name.
- The API key comes from `YOUTUBE_API_KEY` or a key file the user names via `SCOUT_ENV_FILE`.
  Load the user's key file into the environment for the command; never copy the key into the
  repo or print it.
- The repository is private. A visibility change is a separate, explicitly authorised step.
