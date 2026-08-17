# Gyraq-WebScrapper

A Google Maps scraper for local businesses. It drives a real Chromium browser
(via Playwright) to search Google Maps and pull structured business data —
name, category, rating, address, phone, website, weekly hours, coordinates,
and a handful of recent reviews.

It runs as a long-lived Docker container with two ways to feed it work:

- **A YAML queue file** (`data/queries.yaml`) — drop search queries in, it
  works through them continuously, writing a CSV and a JSON file per query.
- **An HTTP API** (`http://localhost:8080`) — for driving it from something
  like n8n. `POST /scrape` to start a search, poll `GET /jobs/{id}` for the
  result as JSON. See [Using it from n8n](#using-it-from-n8n) below.

Both share the same browser/worker, so queries from either source just queue
up behind each other.

> **Note:** this scrapes Google Maps' web UI directly, which is against
> Google's Terms of Service. Use responsibly — the container adds randomized
> delays between actions to behave less like a bot, but that doesn't
> eliminate the risk of Google blocking the IP it runs from.

## Requirements

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose (bundled
  with Docker Desktop on Mac/Windows; on Linux install `docker-compose-plugin`)

That's it — no Python or Playwright install needed on the host, everything
runs inside the container.

## Running it as a container

1. Clone the repo:

   ```bash
   git clone https://github.com/Stradok/Gyraq-WebScrapper.git
   cd Gyraq-WebScrapper
   ```

2. Build and start it in the background:

   ```bash
   docker compose up -d --build
   ```

   This builds the image (first time only takes a few minutes — it installs
   Chromium) and starts the container with `restart: unless-stopped`, so it
   comes back up automatically after a reboot or crash.

3. Add a search by editing `data/queries.yaml`:

   ```yaml
   - query: "plumbers in Denver, CO"
     max_results: 50
   - query: "bakeries in Portland, OR"
     max_results: 30
   ```

   Save the file — no restart needed. The container polls it every 30
   seconds (`POLL_INTERVAL_SECONDS`) and picks up anything without a
   `status` field.

4. Watch it work:

   ```bash
   docker compose logs -f
   ```

5. Grab your results from `data/results/` — each query produces a
   `<query>_<timestamp>.csv` and a matching `.json` file with the same data
   (the JSON also includes the scraped reviews; the CSV folds them into a
   single `top_reviews` column).

### Stopping / restarting

```bash
docker compose down        # stop and remove the container
docker compose up -d       # start it again (reuses the built image)
docker compose up -d --build   # rebuild after pulling code changes
```

### Re-running a query

Each entry in `data/queries.yaml` gets a `status: done` (or `status: error`)
field added once it's processed, plus `result_count`, `csv_path`,
`json_path`, and timestamps. Delete the `status` line (or the whole entry
and re-add it) to have it picked up again.

## Using it from n8n

The container also runs a small HTTP API on port `8080`, published to
`127.0.0.1` only (i.e. reachable from the same machine, not the rest of the
network — see the note below if n8n itself runs in Docker).

**1. Start a scrape** — `POST` a query, get back a job id immediately:

```bash
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -d '{"query": "gyms in Chicago, IL", "max_results": 20}'
```
```json
{"job_id": "fec0c255a123", "status": "queued", ...}
```

**2. Poll for the result** — scrapes take anywhere from a few seconds to a
few minutes depending on `max_results`, so poll until `status` is `done` (or
`error`):

```bash
curl http://localhost:8080/jobs/fec0c255a123
```
```json
{
  "job_id": "fec0c255a123",
  "status": "done",
  "result_count": 20,
  "results": [ { "name": "...", "address": "...", "phone": "...", "reviews": [...] }, ... ],
  "csv_path": "/app/data/results/gyms_in_chicago_il_....csv",
  "json_path": "/app/data/results/gyms_in_chicago_il_....json"
}
```

**In n8n**, this is two HTTP Request nodes:

- **HTTP Request** (POST) → `http://localhost:8080/scrape`, JSON body
  `{"query": "...", "max_results": ...}` → returns `job_id`.
- **HTTP Request** (GET) → `http://localhost:8080/jobs/{{ $json.job_id }}`,
  wired into a **Wait** node + loop (or the "retry on fail" option) until
  `status` isn't `queued`/`running` — then the `results` array is ready to
  feed into the rest of the workflow.

Other endpoints: `GET /jobs` lists every job with its status, `GET /health`
is a plain liveness check.

> **If n8n also runs in Docker** on the same laptop, `localhost` inside the
> n8n container won't reach the scraper container. Either put both in the
> same `docker-compose.yml` / Docker network and call it by service name
> (`http://scraper:8080`), or run n8n with `--network host`.

## Deduplication

By default, the scraper remembers every business it has ever returned
(keyed by Google's internal place ID, extracted from the listing URL) in
`data/seen_places.txt`. Overlapping or repeated searches — including across
container restarts, since that file lives in the mounted `data/` folder —
skip anything already captured instead of re-scraping it, and the skip
happens *before* opening the listing page, not after.

To re-scrape everything fresh, delete `data/seen_places.txt`. To disable
deduplication entirely, set `SKIP_ALREADY_SEEN=false`.

## Configuration

Set these as environment variables (see `docker-compose.yml`):

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `30` | How often to check `queries.yaml` for new work |
| `DELAY_BETWEEN_QUERIES_MIN` / `_MAX` | `20` / `60` | Random pause between queries, in seconds |
| `REVIEWS_PER_BUSINESS` | `5` | Max recent reviews to capture per business |
| `SKIP_ALREADY_SEEN` | `true` | Skip businesses already captured in a previous run |
| `DEFAULT_MAX_RESULTS` | `60` | Used when a query entry doesn't set `max_results` |
| `HEADLESS` | `true` | Set to `false` to run Chromium with a visible window (needs a display) |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `API_PORT` | `8080` | Port the HTTP API listens on inside the container |

## Project layout

```
Dockerfile / docker-compose.yml   container + Chromium setup
data/queries.yaml                 the job queue (mounted volume)
data/results/                     CSV/JSON output (mounted volume)
src/main.py                       entrypoint: starts the API + worker thread
src/api.py                        HTTP API (FastAPI): POST /scrape, GET /jobs/{id}
src/jobs.py                       in-memory job store shared by the API and worker
src/queue_runner.py               worker loop: drains API jobs, then queries.yaml
src/maps_scraper.py               Playwright scraping logic
src/exporter.py                   CSV/JSON writers
src/models.py                     Business/Review data model
src/config.py                     environment variable settings
```
