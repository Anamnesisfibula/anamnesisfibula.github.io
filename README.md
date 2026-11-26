# Fibula tracker

Static page (GitHub Pages) + GitHub Actions that refresh data from opentibia.info.

- `data/network.json`: owners (clusters), their linked characters and char info.
- `data/status.json`: tracked characters online right now (every ~10 min).
- `data/changes.json`: log of new alts and new guild members found by the nightly scan.
- Run manually: Actions → Update tracker → Run workflow (mode `online` or `scan`).
- Exiva tab (BETA): players enter exiva results cast from known depots; the page draws where they overlap. Hunts are shared through the same Cloudflare worker as Suggest alt (`/exiva/*`, tables `hunt` and `reading`). Map image from TibiaMaps.io tibia-map-data.
