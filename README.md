# Gyraq-WebScrapper

A Google Maps scraper for local businesses. It drives a real Chromium browser
(via Playwright) to search Google Maps and pull structured business data —
name, category, rating, address, phone, website, weekly hours, coordinates,
and a handful of recent reviews.

It runs as a long-lived Docker container: you drop search queries into a
YAML file, and it works through them continuously, writing a CSV and a JSON
file per query.

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

## Configuration

Set these as environment variables (see `docker-compose.yml`):

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `30` | How often to check `queries.yaml` for new work |
| `DELAY_BETWEEN_QUERIES_MIN` / `_MAX` | `20` / `60` | Random pause between queries, in seconds |
| `REVIEWS_PER_BUSINESS` | `5` | Max recent reviews to capture per business |
| `DEFAULT_MAX_RESULTS` | `60` | Used when a query entry doesn't set `max_results` |
| `HEADLESS` | `true` | Set to `false` to run Chromium with a visible window (needs a display) |
| `LOG_LEVEL` | `INFO` | Python logging level |

## Project layout

```
Dockerfile / docker-compose.yml   container + Chromium setup
data/queries.yaml                 the job queue (mounted volume)
data/results/                     CSV/JSON output (mounted volume)
src/main.py                       entrypoint, logging setup
src/queue_runner.py               watches queries.yaml, drives the loop
src/maps_scraper.py               Playwright scraping logic
src/exporter.py                   CSV/JSON writers
src/models.py                     Business/Review data model
src/config.py                     environment variable settings
```
