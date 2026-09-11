# Publishing notice

This repository is private. If it is ever made public, the boundaries below apply.

## What can be public

- The skill code, tests, fixtures with invented data, installers, and documentation.
- Aggregate, non-identifying examples of output (a top-10 table of public video titles and
  channel handles is acceptable; full comment or transcript dumps are not).

## What must stay private

- API keys, tokens, cookies, `.env` files, and any key file path specific to one machine.
- Generated workbooks. They hold third-party creator names, comments, and transcripts collected
  for research, and they must not be redistributed.
- Client spreadsheets and anything derived from them.
- Local absolute paths and usernames.

## Rights boundary

Public availability of a YouTube video, comment, or caption does not create permission to
redistribute it. The skill collects public metadata for the user's own research. Publish
summaries and links, not bulk copies.

## Review before any visibility change

1. Run the secret scan across tracked files and the full git history.
2. Run the hygiene test for paths and workbooks.
3. Confirm the license, the README, and the changelog are current.
4. Confirm repository visibility and any Pages visibility separately.
5. Get explicit authorisation naming the repo, branch, visibility, and tag.
