# Security Policy

## Reporting

Please do not report security issues in public GitHub issues.

If you find a vulnerability or accidentally exposed secret, contact the maintainer privately through GitHub profile contact options and include:

- A short description of the issue.
- Steps to reproduce when possible.
- Any affected files, commands, or configurations.

## Sensitive Data

Lifeboard can use AI provider keys, Finnhub keys, CoinGecko keys, Telegram bot tokens, private board contents, local image paths, and rendered wallpaper images. These should stay out of the repository.

Expected private locations:

- `~/.lifeboard/secrets.json`
- `~/.lifeboard/config.json`
- `~/.lifeboard/board.json`
- `~/.lifeboard/output/`

The repository `.gitignore` excludes common local copies of these files, but contributors should still review diffs before publishing.

