# Data pipeline

One-off scripts that build and maintain the SQLite database and the ChromaDB store. All of them read and write inside the data folder (`AK_DATA_DIR`, default `local_data/`; see `backend/app/paths.py`). Most of them resume from a checkpoint. Before running anything that calls a web API, set `AK_CONTACT_EMAIL` to your own address (see the main [README](../README.md#configure)).

| Script | Purpose |
|---|---|
| `import_gbif.py` | Download and import the GBIF Backbone Taxonomy (the original taxonomy) |
| `import_col.py` | Load a Catalogue of Life ColDP release into its own SQLite database |
| `compare_col.py` | Compare a COL release with the GBIF tree (needs the GBIF backbone) |
| `verify_col_levels.py` | Check orders and families COL leaves blank against independent sources (Global Names) |
| `build_col_db.py` | Build the app's `species` table from COL, carrying over collected data; never overwrites |
| `backfill_extinct.py` | Extinct flags: fossil species and all-extinct groups (`--rollup-only` after a COL build) |
| `fix_common_names.py` | Reviewed tree labels for phyla, classes and orders |
| `fix_name_collisions.py`, `batch_extinct_gbif.py` | GBIF-era one-offs, kept for the record |
| `enrich_iucn.py` | IUCN Red List status, trend, habitat, elevation (needs `IUCN_API_TOKEN`) |
| `enrich_anage.py` | Lifespan, body mass and metabolic rate from AnAge |
| `enrich_wikipedia.py` | Wikipedia summaries and thumbnails |
| `enrich_images.py` | Pictures from iNaturalist and other sources |
| `enrich_gbif_occurrences.py` | Ranges from a sample of GBIF occurrences (superseded by `import_gbif_ranges.py`) |
| `gbif_download.py` | Request, check and fetch the two GBIF SQL occurrence downloads (`ranges`, `countries`); needs a free GBIF account |
| `import_gbif_ranges.py` | Ranges from a GBIF SQL occurrence download |
| `import_gbif_countries.py` | Wild records per species per country from a GBIF SQL download |
| `build_places.py` | Natural Earth places for the chat's "animals of a place" |
| `build_embeddings.py` | Embed the Wikipedia summaries into ChromaDB |
| `validate_import.py` | Row counts and required fields |
| `chat_eval.py` | Live chat check with a tool trace; `--suite` scores a model |
