# Animal Kingdom — User Manual

An offline-first app cataloguing ~1.78 million animal species with an interactive taxonomy tree and a local AI chatbot.

---

## What you need before starting

This section is a checklist, not an installation guide; the [README](../README.md#building-and-running) covers installing and building.

| Component | Location / command to verify |
|---|---|
| Python 3.12 venv | `.venv` in the project root |
| Species database | `<data dir>\species.db` (~5.9M rows); the data folder is `AK_DATA_DIR` in `.env`, default `local_data\` |
| Ollama (AMD AI Bundle) | Running as a background app — check system tray |
| LLM model | `ollama list` → should show `llama3.1:8b` |

---

## Quick start (one-click)

If you just want everything running without opening multiple terminals:

1. Make sure **Ollama is running** first (system tray, or Start Menu → Ollama)
2. Double-click **`start.bat`** in the project root — it starts the backend and frontend in the background, then opens the browser automatically
3. Double-click **`stop.bat`** when you're done

Or from a terminal:
```bash
python manage.py start    # start all services + open browser
python manage.py stop     # stop all services
python manage.py status   # show what's running
```

---

## Step 1 — Make sure Ollama is running

Ollama runs as a background Windows application from the AMD AI Bundle. If it isn't running:

1. Open **Start Menu** → search for **Ollama** → launch it
2. Confirm it's up: open a terminal and run:
   ```
   ollama list
   ```
   You should see `llama3.1:8b` in the list. If the list is empty, pull the model:
   ```
   ollama pull llama3.1:8b
   ```
   *(~4.9 GB download — only needed once)*

---

## Step 2 — Start the backend

Open a terminal, navigate to the project, and start the FastAPI server:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

**Quick health check** — open a browser and go to:
```
http://localhost:8000/health
```
You should see `{"status":"ok"}`.

> **Keep this terminal open.** The backend must stay running while you use the app.

---

## Step 3 — Open the app

Go to **http://localhost:8000** in your browser.

The backend serves both the API and the frontend — no second terminal needed.

The app has two panels:

| Panel | What it does |
|---|---|
| **Left — Taxonomy Tree** | Interactive zoomable tree of all ~1.78M species |
| **Right — Chat** | AI chatbot powered by local Llama 3.1 |

---

## Using the Taxonomy Tree

### Navigate
- **Scroll** to zoom in/out
- **Click and drag** on empty space to pan
- **Click a node** to expand it and load its children
- **Click an expanded node** to collapse it back

### Colours
Each dot is colour-coded by taxonomic rank. The key is also shown in the bottom-left corner of the tree, and stays there while you pan or zoom:

| Colour | Rank |
|---|---|
| 🩷 Pink | Domain |
| 🔴 Red | Kingdom |
| 🟠 Orange | Phylum |
| 🟡 Yellow | Class |
| 🟢 Green | Order |
| 🔵 Blue | Family |
| 🟣 Purple | Genus |
| 🩵 Teal | Species |
| ⚪ Grey | Other ranks, e.g. Viruses, unranked groups |

A **ring** (coloured outline, dark centre) is a node you opened and closed again, or a search path showing only one branch; it keeps its rank colour. The **amber** dot is the selected node.

### Domains
The tree starts at the three domains of life, **Bacteria**, **Archaea** and **Eukarya**, with **Viruses** beside them because they belong to no domain. Eukarya opens on load to show its five kingdoms. Searching "Bacteria" or "Archaea" offers both the domain and the animal genus of the same name.

### Extinct taxa (†)
Fossil taxa are marked **†** and drawn with a grey label, e.g. "† Tapirus merriami". Tick **Hide extinct (†)** in the header to leave them out of the tree. Each branch then ends in a "† N extinct hidden" entry; click it to show them again. The setting is remembered between visits. A searched-for or selected fossil always stays visible.

No † means "living or not yet known". About 140,000 animal taxa are flagged from the GBIF backbone (see *Optional enrichment*). Others get the flag when you first open their panel.

### Search
Type a species name (scientific or common) in the **Search species…** bar at the top. After 300 ms:
- A dropdown appears with up to 20 matching species: exact names first, then animals with the term as a word in a common name ("wombat" finds the common wombat before *Wombatus*), then scientific names starting with it
- Old names are tagged, e.g. "Malayan Tapir — *Tapirus indicus* (old name of Acrocodia indica)"
- Matching nodes in the tree are highlighted; non-matching nodes fade out
- Click a result to select it
- Clear the search bar to restore full tree visibility

**Pictures:** the panel looks a picture up online the first time it opens an animal (Wikipedia, iNaturalist, Wikimedia Commons, DuckDuckGo) and keeps it. When none is found, the picture area says **No picture found.** with a **Search again** button. It searches wider: the current name of an old name, and photos attached to GBIF records. For obscure animals those are often museum specimens, marked "(museum specimen)" after the source. "Still no picture after a wider search." means nothing turned up; "A picture source didn't answer" means a source was busy or offline, so nothing was recorded and you can try again later.

**Wrong picture?** Click **Other pictures** under the picture. The panel asks every source at once and shows what came back within 10 seconds: up to 12 thumbnails, each with its source; hover one for its photographer and licence. If a source was too slow, a line says so, and clicking **Other pictures** again may find more. Click the one you want and it's kept. The picture it replaces is remembered and never offered again, also not by the automatic lookup. If saving fails, the thumbnails stay so you can click again. **Cancel** brings the old picture back. The button is also there when no picture was found; it waits while **Search again** runs. If a kept picture later stops loading, the panel looks for another one and skips the broken link that time (it isn't rejected for good: offline, every picture fails to load).

**Old names:** the panel of an old name shows a **Current name** row with a link to the animal it now belongs to, and where the link comes from. Most links come from the Catalogue of Life. Some old names are still listed there as separate species (*Tapirus malayanus*); for those the link comes from Wikidata's "taxon synonym of" and appears once the panel has looked the name up online.

---

## Using the Chat

Type a question in the **Ask about a species…** box at the bottom right and press **Enter** or click **Send**.

The AI looks up facts directly from the local species database before answering. Good questions to try:

| Question type | Example |
|---|---|
| Species facts | *Tell me about Panthera leo* |
| Taxonomy | *What is the taxon path for Canis lupus?* |
| Ecology | *What animals live in the savanna?* |
| Conservation | *Which species are critically endangered felids?* |
| Common name → scientific name | *What is the scientific name of the eagle owl?* |
| Rankings | *Which animal can get oldest?* · *What is the heaviest bird?* · *Which penguins live furthest north?* |
| Group counts | *How many owl species are endangered?* · *How many mammals have gone extinct?* |
| Relationships | *What is a whale related to?* · *Which orders do mammals have?* |
| Animals of a place | *Which snakes can be found in Holland?* · *What owls live on Borneo?* · *Which lemurs live in Madagascar?* |
| Countries of an animal | *In which countries can I find tigers?* · *Where do gorillas live?* |

Rankings only cover species with a recorded value (about 4,000 lifespans and 3,600 body masses), and the values are the maximum recorded or estimated, not typical ages. North/south rankings use the geographic ranges built from wild GBIF observations (about 172,000 species in the panel; rankings use the about 27,500 with 1,000 or more records, so one stray record can't set an edge). The outer 0.5% of records is left out so zoo animals don't count, which means a true range can reach slightly further. Extinct counts include fossil species.

**Animals of a place** works for countries, continents, islands, regions (the Alps, the Sahara, the Amazon) and seas. For a country, the chat lists species with wild GBIF sightings there, most recorded first; species seen far less often (escaped pets, strays, rarely seen species) are counted but not listed, and a country with no sightings at all gets a plain answer ("no wild records of snakes in Ireland"). A continent works the same way through its countries (Russia, Turkey and a few other countries on two continents count only for species whose range reaches that continent; "Oceania" is the continent Australia). For islands, regions and seas it lists species whose GBIF range overlaps the place, closest fit first. A range is a box around the records, so an overlap means a species *may* live there, and only species with 1,000 or more records count. Snakes, lizards, sharks and marsupials have no single group in the Catalogue of Life, so the chat uses fixed lists of their families or orders: "snakes" are the snake families, "lizards" the other squamate families without the worm lizards, "sharks" the nine shark orders (not the rays), "marsupials" the seven marsupial orders. This works for places, rankings ("the longest-living shark") and counts ("how many sharks are endangered"); the tree itself still shows the Catalogue of Life's classification.

**Countries of an animal** come from the same GBIF sightings per country. The chat lists the countries where the animal is recorded well, plus neighbouring countries that have sightings too; sightings far from those (tigers in zoos in Brazil, koalas in Japan) are counted but not listed. GBIF counts domestic dogs as wolves, so the wolf seems to live almost everywhere.

**Follow-up questions:** the chat remembers the last three questions and answers on the page, so you can ask *What is the largest animal?* and then *What does it eat?* Reloading the page starts a new conversation.

**Name links:** names in an answer are links (dotted underline) when the chat looked them up in the database. A scientific name of a species in the tree (*Pygoscelis adeliae*) is a link even in a general-knowledge sentence. Click one to open it in the tree and the species panel, as a search result does; hover shows its scientific name and rank. Animals named only by a common name from general knowledge (the krill a whale eats) stay plain text. Links appear when the answer has finished, and are gone after a page reload.

**Chat model:** the chat uses `llama3.1:8b`. To try another Ollama model, pull it and set it before starting the app, e.g. in a terminal: `set AK_CHAT_MODEL=qwen3.8:27b` then `start.bat`. If the model isn't installed, the chat shows Ollama's "model not found" error. A larger model is slower, and its first answer after a few idle minutes takes longer while Ollama loads it (about 20 s for a 17 GB model). qwen3.8:27b needs Ollama 0.40.16 or newer to be fast on AMD. In the November 2026 comparison it was not better than llama3.1:8b for this app (see `Docs/PLAN.md`, Increment 22).

**What to expect:**
- The response streams in word-by-word (live, token by token)
- If a species image is available in the database, it appears below the response
- The input is locked while the AI is responding and re-enables when done

**Note on response time:** The first message after a period of inactivity may take 5–10 seconds longer while the model loads back into GPU memory. Subsequent messages are faster.

---

## Stopping the app

- **If you used `start.bat`:** double-click **`stop.bat`**, or run `python manage.py stop`
- **If you started manually:** press **Ctrl + C** in each terminal
- Ollama can be left running — it unloads models from memory automatically after a few minutes of inactivity

---

## Troubleshooting

### Tree doesn't load
- Make sure the backend is running on port 8000
- Check the backend terminal for error messages
- Reload the browser page

### Chat says "error" or doesn't respond
- Confirm Ollama is running: `ollama list`
- Confirm the backend is running: `http://localhost:8000/health`
- If Ollama was just started, wait 10 seconds and try again

### Search returns no results
- The search is a substring match — try a shorter term
- Scientific names work best (e.g. `Panthera` rather than `big cats`)

### Backend fails to start — port already in use
```bash
# Find and kill whatever is on port 8000
netstat -ano | findstr :8000
taskkill /F /PID <PID shown above>
```

### Backend fails to start — database not found
Make sure the data folder (`AK_DATA_DIR`) is reachable, for example that its drive is connected. The database lives at:
```
<data dir>\species.db
```

---

## Optional enrichment (improves chat quality)

The database currently has taxonomy data for all species. Two enrichment scripts can add abstracts and images:

### Wikipedia enrichment *(no account needed)*
```bash
cd <project folder>
python data/enrich_wikipedia.py --only-with-common-names --animals-only --batch-size 200000
```
Takes about 1.3 seconds per species (a half-second pause plus Wikipedia's reply), so roughly 40–45 hours for the ~125,000 animals with a common name and no description, spread over several sessions. Stop it any time and run the same command again to resume; it checkpoints every 1,000 species. A Wikipedia thumbnail only fills a species that has no image yet. Afterwards rebuild the search index (*Build embeddings* below).

### IUCN Red List enrichment *(free API token required)*
Get a token from [apiv3.iucnredlist.org](https://apiv3.iucnredlist.org), then:
```bash
python data/enrich_iucn.py --token YOUR_TOKEN_HERE
```

### Extinct flags *(offline, ~20 s)*
Marks genera, families and other groups whose species are all extinct. Run it after a Catalogue of Life build:
```bash
python data/backfill_extinct.py --rollup-only --dry-run   # counts only
python data/backfill_extinct.py --rollup-only
```
Without `--rollup-only` it first marks Paleobiology Database species from the GBIF backbone (`Taxon.tsv`). That backbone was deleted on 2026-11-10, so this pass, and `batch_extinct_gbif.py` below, need it downloaded again.
Safe to re-run; it never overwrites an existing value.

Then, for fossils listed by other sources, ask GBIF about each unknown species in a genus that holds a known fossil (internet needed, ~75 min):
```bash
python data/batch_extinct_gbif.py --sample 300   # speed test, writes nothing
python data/batch_extinct_gbif.py                # stop any time; re-run to resume
```

### Name-collision repair *(offline, ~10 min, one-off)*
The database keeps one row per name. Imports before 2026-11-04 kept the first backbone row of each name, so an outdated synonym could stand in for an accepted animal: "Panthera" was a moth synonym, and selecting it jumped to *Pantherodes*. This replaces such rows with the accepted animal (highest rank wins for homonyms) and backs up the originals first:
```bash
python data/fix_name_collisions.py --dry-run   # counts only
python data/fix_name_collisions.py             # originals -> <data dir>
ame_collisions_backup.jsonl
python data/backfill_extinct.py                # re-derive extinct flags for the replaced rows
```
Safe to re-run; a fresh import no longer needs it.

### Common-name corrections *(offline, seconds, one-off)*
The tree labels a group with its first stored common name, which could be wrong: Mammalia showed as "Herbivore" and Myxini (hagfish) as "fish". This applies a hand-reviewed list of corrections to phyla, classes and orders. Re-run it after a fresh import:
```bash
python data/fix_common_names.py --dry-run   # shows each change, writes nothing
python data/fix_common_names.py             # old values go to <data dir>/common_names_backup.jsonl
```
Safe to re-run.

### GBIF ranges *(offline, ~15 min; re-run after a Catalogue of Life build)*
The species panel's **Range** row and the chat's north/south rankings come from one GBIF download of wild observations (2.59 billion records, DOI 10.15468/dl.5v8cu8), kept in `<data dir>\gbif_ranges\`. A range that crosses the 180° line (polar bear) shows its latitudes only.
```bash
python data/import_gbif_ranges.py --dry-run   # counts only
python data/import_gbif_ranges.py             # old ranges -> <data dir>/gbif_ranges_backup.jsonl
```
Safe to re-run. A fresh download needs a GBIF login (`GBIF_USER` / `GBIF_PASSWORD`, or `<data dir>\gbif_credentials.json`) and `python data/gbif_download.py ranges submit` (about an hour on GBIF's side); `status` and `fetch` follow the same pattern.

### Build embeddings *(run after Wikipedia enrichment)*
Once abstracts are populated, build the semantic search index:
```bash
python data/build_embeddings.py
```
This enables the chatbot to find species by meaning, not just exact name.
