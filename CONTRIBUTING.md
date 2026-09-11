# Contributing

Thanks for helping improve youtube-scout. The repository is private for now, so contributions
come from invited collaborators.

## Ground rules

- Keep the skill dependency-light: the standard library plus openpyxl. yt-dlp stays optional
  and is only used behind `--hooks` and `--download`.
- Never commit API keys, `.env` files, generated workbooks, downloaded media, or the probe
  cache. The `.gitignore` and the hygiene test enforce this; do not weaken them.
- No em dashes anywhere: code, comments, docs, commit messages. Use commas, periods, colons,
  or parentheses.
- Every behaviour change ships with a test. The suite is offline; add fixtures shaped like real
  API responses under `tests/fixtures/` with invented ids and names.

## Workflow

1. Branch from `main`.
2. Make the change and run `python -m pytest` and `ruff check .`.
3. Run the secret and path scan: `detect-secrets-hook --baseline .secrets.baseline $(git ls-files)`.
4. Open a pull request using the template. Squash or rebase merges only.

## Commit messages

Imperative sentence case, no trailing period, for example `Add breakout sort` or
`Fix caption rate limit handling`. Sign commits with `Signed-off-by` (`git commit -s`).

## Releases

Follow `RELEASE_CHECKLIST.md`. Bump the version in `pyproject.toml`,
`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and `CHANGELOG.md` together.
