# US Pulse

A public, data-only dashboard for US markets, published with GitHub Pages.
It reads market data and renders it. It never connects to a broker and never places orders.

## Layout

- `pipeline/` data-building code
- `tests/` automated tests
- `tools/` helper scripts, including `scan_repo.py` (secret and broker-code scanner)
- `data/` committed CSV outputs only
- `docs/` the published site
- `.github/workflows/` CI and scheduled jobs

## Development

    python -m pytest tests -q
    python tools/scan_repo.py

## Security checklist for the owner

This repository is public, so everything committed is visible to everyone.

- [ ] Turn on 2-factor sign-in on your GitHub account.
- [ ] Settings -> Actions -> General: restrict Actions to selected actions, and set workflow permissions to read.
- [ ] Protect the `main` branch (require pull requests and passing checks).
- [ ] Never commit raw or private data (pickles, caches, `.env`, tokens). Only reviewed CSV outputs belong in `data/`.
- [ ] Remember: the repo is public, so nothing secret, personal, or account-related may ever be committed.
