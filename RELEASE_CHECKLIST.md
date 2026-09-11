# Release checklist

Work through every item before tagging. Items are grouped by concern.

## Product

- [ ] README states the promise, who it is for, what it outputs, how to install, and limits.
- [ ] `SKILL.md` matches the flags and exit codes in `scripts/scout.py`.
- [ ] `CHANGELOG.md` has an entry for this version with today's date.
- [ ] Version is identical in `pyproject.toml`, `.claude-plugin/plugin.json`,
      `.claude-plugin/marketplace.json`, and the top `CHANGELOG.md` heading.

## Verification

- [ ] `python -m pytest` passes.
- [ ] `ruff check .` passes.
- [ ] One live `--dry-run` against the API works with the key loaded from the environment.
- [ ] `./install.sh --target claude` into a temporary `YOUTUBE_SCOUT_INSTALL_HOME` works and
      the installed copy runs `--help`.

## Publish safety

- [ ] `detect-secrets-hook --baseline .secrets.baseline $(git ls-files)` is clean.
- [ ] The regex gate in `.github/workflows/ci.yml` is clean locally.
- [ ] `tests/test_repo_hygiene.py` passes: no em dashes, no local absolute paths, no key file
      references, no tracked `.xlsx`.
- [ ] `git log -p --all | grep -nE '<credential regex>'` across full history is clean.
- [ ] `git status --ignored` shows workbooks, downloads, and cache as ignored, never staged.
- [ ] Repository visibility is what was authorised. A public flip is a separate decision and
      follows the consent rule: name the repo, branch, visibility, and tag before pushing.

## Tag and release

- [ ] Commit with `Signed-off-by`, push `main`, confirm CI is green.
- [ ] `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <notes>`.
- [ ] Reinstall from the tag and smoke test once more.
