# Fibula tracker

Static page (GitHub Pages) + GitHub Actions that refresh data from opentibia.info.

- `data/network.json`: owners (clusters), their linked characters and char info.
- `data/status.json`: tracked characters online right now (every ~10 min).
- `data/changes.json`: log of new alts and new guild members found by the nightly scan.
- Run manually: Actions → Update tracker → Run workflow (mode `online` or `scan`).
