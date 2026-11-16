# Species Database Schema

**File:** `E:\AnimalKingdomSystem\species.db`  
**Engine:** SQLite (WAL mode enabled)

---

## Table: `species`

Primary key: `scientific_name` (canonical name without authorship, e.g. `Panthera leo`)

| Column | Type | Description |
|--------|------|-------------|
| `scientific_name` | TEXT PK | Canonical scientific name — unique identifier |
| `taxon_path` | TEXT | Pipe-delimited lineage, e.g. `Animalia\|Chordata\|Mammalia\|Carnivora\|Felidae\|Panthera\|Panthera leo` |
| `taxon_rank` | TEXT | Rank in lowercase: `kingdom`, `phylum`, `class`, `order`, `family`, `genus`, `species`, `subspecies`, … |
| `common_names` | TEXT | JSON array of strings, e.g. `["Lion", "African lion"]` |
| `taxonomic_status` | TEXT | `ACCEPTED` or `SYNONYM` |
| `body_mass` | REAL | Body mass in kilograms |
| `body_length` | REAL | Body length in metres |
| `max_lifespan` | REAL | Maximum recorded lifespan in years |
| `metabolic_rate` | REAL | Basal metabolic rate (W) |
| `reproduction_strategy` | TEXT | Free text, e.g. `oviparous`, `viviparous`, `semelparity` |
| `geo_bounding_box` | TEXT | JSON object: `{"lat_min", "lat_max", "lon_min", "lon_max", "records", "countries"}` — see below |
| `habitat_type` | TEXT | e.g. `terrestrial`, `marine`, `freshwater`, `arboreal` |
| `elevation_limits` | TEXT | e.g. `0–4500 m` |
| `trophic_level` | TEXT | e.g. `herbivore`, `carnivore`, `omnivore`, `detritivore` |
| `activity_period` | TEXT | e.g. `diurnal`, `nocturnal`, `crepuscular` |
| `iucn_status` | TEXT | IUCN Red List category: `LC`, `NT`, `VU`, `EN`, `CR`, `EW`, `EX`, `DD`, `NE` |
| `population_trend` | TEXT | `Increasing`, `Stable`, `Decreasing`, `Unknown` |
| `primary_image_url` | TEXT | Direct URL to a representative image |
| `image_attribution` | TEXT | Attribution/licence text or source URL for the image |
| `wikipedia_abstract` | TEXT | Plain-text summary from the Wikipedia REST API |

### Indexes

| Index name | Column | Purpose |
|------------|--------|---------|
| `idx_taxon_rank` | `taxon_rank` | Filter by rank (e.g. all genera) |
| `idx_taxonomic_status` | `taxonomic_status` | Separate accepted taxa from synonyms |
| `idx_iucn_status` | `iucn_status` | Filter by conservation status |
| `idx_taxon_path` | `taxon_path` | LIKE prefix queries for tree zoom (`taxon_path LIKE 'Animalia|Chordata|%'`) |

---

## JSON field conventions

Both JSON columns are serialised/deserialised exclusively through helpers in `backend/app/database.py` — never manipulate the raw strings directly.

**`common_names`**
```json
["Lion", "African lion"]
```
Helpers: `parse_common_names(json_str)` / `serialize_common_names(names)`

**`geo_bounding_box`**
```json
{ "lat_min": -38.54, "lat_max": -26.39, "lon_min": 138.56, "lon_max": 153.57, "records": 350798, "countries": 9 }
```
Helpers: `parse_geo_bbox(json_str)` / `serialize_geo_bbox(bbox)`; rules in `backend/app/geo_range.py`.
- Since Increment 24, edges are the 0.5% / 99.5% percentiles of a species' wild GBIF records, from at least 10 records: `data/import_gbif_ranges.py` (GBIF SQL download, ~172k species), or the panel's on-demand sample of up to 300 records.
- `records` = wild records used; `countries` = distinct countries (bulk import only).
- A longitude span over 340° crosses the 180° line: `lon_min` / `lon_max` are then left out (latitude-only range, e.g. the polar bear).
- Older rows may hold only the four edges (raw min/max), or a broken `{}`; a range needs both latitudes to show or rank.

---

## `taxon_path` conventions

- Separator: `|` (pipe)
- Components: the canonical name of each ancestor rank, from kingdom down to the node itself
- Higher-rank nodes include only the levels that exist (empty hierarchy fields are omitted)
- Prefix queries use `LIKE 'path|%'` — supported by `idx_taxon_path`
- Depth at a node = number of `|` characters in its `taxon_path`

| Rank | Example `taxon_path` |
|------|---------------------|
| Kingdom | `Animalia` |
| Phylum | `Animalia\|Chordata` |
| Class | `Animalia\|Chordata\|Mammalia` |
| Order | `Animalia\|Chordata\|Mammalia\|Carnivora` |
| Family | `Animalia\|Chordata\|Mammalia\|Carnivora\|Felidae` |
| Genus | `Animalia\|Chordata\|Mammalia\|Carnivora\|Felidae\|Panthera` |
| Species | `Animalia\|Chordata\|Mammalia\|Carnivora\|Felidae\|Panthera\|Panthera leo` |

---

## Data sources by column

| Source | Columns populated |
|--------|------------------|
| GBIF Backbone Taxonomy (`import_gbif.py`) | `scientific_name`, `taxon_path`, `taxon_rank`, `common_names`, `taxonomic_status` |
| IUCN Red List API (`enrich_iucn.py`) | `iucn_status`, `population_trend` |
| Wikipedia REST API (`enrich_wikipedia.py`) | `wikipedia_abstract`, `primary_image_url`, `image_attribution` |
| GBIF SQL download (`import_gbif_ranges.py`, Increment 24) | `geo_bounding_box` |
| Future / manual | `body_mass`, `body_length`, `max_lifespan`, `metabolic_rate`, `reproduction_strategy`, `habitat_type`, `elevation_limits`, `trophic_level`, `activity_period` |

## Catalogue of Life columns (Increment 16)

| Column | Meaning |
|---|---|
| `col_id` | COL `ID` of the name usage; NULL for rows COL lacks |
| `accepted_name` | For a synonym, the accepted name it points to |
| `gbif_taxon_path` | Old GBIF path, for rows COL lacks (`taxonomic_status = 'GBIF_ONLY'`, `taxon_path` NULL) |

`taxon_fixes(level, grp, phylum, value, sources, applied)` lists every confirmed family or order and whether it reached the tree.
