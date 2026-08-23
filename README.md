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
> delays between actions and applies [playwright-stealth](https://github.com/AtuboDad/playwright_stealth)
> (patches common automation fingerprints like `navigator.webdriver`) to
> every page it opens, including the extra pages used for the email lookup
> below, but neither eliminates the risk of a site or Google blocking the
> IP it runs from.

Two setup paths, pick one:

- **Docker** (recommended for the always-on/server case) — one dependency
  (Docker), fully isolated, `restart: unless-stopped` survives reboots.
- **Native, via `uv`** (recommended if Docker feels heavy, or for quick
  local runs) — one tool (`uv`) sets up Python, installs everything, and
  runs it, on both Windows and Linux with the same two commands.

## Option A: Docker

### Requirements

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose (bundled
  with Docker Desktop on Mac/Windows; on Linux install `docker-compose-plugin`)

That's it — no Python or Playwright install needed on the host, everything
runs inside the container.

### Running it as a container

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

## Option B: Native, via `uv` (no Docker)

Same functionality, running directly on your machine instead of in a
container — useful if you don't want Docker installed at all. Works
identically on Windows and Linux; [uv](https://docs.astral.sh/uv/) is a
single cross-platform binary that handles the Python install, virtual
environment, and dependencies for you.

**Linux / macOS:**
```bash
git clone https://github.com/Stradok/Gyraq-WebScrapper.git
cd Gyraq-WebScrapper
./setup.sh   # installs uv (if missing), deps, and the Chromium browser
./run.sh     # starts it — same behavior as the Docker container
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/Stradok/Gyraq-WebScrapper.git
cd Gyraq-WebScrapper
.\setup.ps1
.\run.ps1
```

That's it — two commands each. `setup` is a one-time step; after that,
`run` is all you need. Everything else (the queue file, results, the web
UI, the API) behaves exactly the same as the Docker version, just reading
paths relative to the repo folder instead of `/app`.

One Linux-only wrinkle: Playwright's system-library installer
(`playwright install-deps`) needs `sudo`, which `setup.sh` can't run
non-interactively. If Chromium fails to launch on a fresh Linux install,
run `sudo uv run playwright install-deps chromium` once — Docker doesn't
have this issue since the base image already includes those libraries.

## Web UI & monitoring from your phone

Both setup paths serve a small web page at `http://localhost:8080` (or
whatever `API_PORT` you set) — a live view of running/finished searches
and generated drafts, auto-refreshing every few seconds. No install, it's
just a page your browser loads.

It also shows an actual **live screenshot** of the page the browser is on
right now (the search results, or whichever business listing it's
currently reading), refreshed every ~1.5s — so you can watch it work
instead of just seeing a status badge. The scraper stays headless (no
visible browser window) for portability; this gets you the same visual
feedback without needing X11/VNC forwarding, and it works identically from
a phone since it's just an image over HTTP.

To check it from your phone on the same WiFi:

1. Find the laptop's local network IP:
   - **Windows**: `ipconfig` → look for "IPv4 Address" (something like `192.168.1.42`)
   - **Linux**: `hostname -I` or `ip addr`
2. On your phone's browser, go to `http://<that-ip>:8080` — e.g. `http://192.168.1.42:8080`.

This works because the port is published on all network interfaces, not
just `localhost` — which also means **anything else on the same WiFi can
reach it too**, with no login. Fine for a home/office network; if that's a
concern, put it behind your router's firewall rules or a VPN rather than
exposing it further.

### Installing it as an app

The page is a installable PWA (manifest + icons + service worker) — on the
laptop itself (`http://localhost:8080`), Chrome/Edge will offer an
**"Install app"** button right in the header, and it opens afterward in
its own window with no browser chrome, like a native app.

On your **phone**, from Chrome's `⋮` menu choose **"Add to Home screen"**
— you'll get a home-screen icon that opens full-screen, no address bar.
One honest caveat: the *automatic* install banner and full offline support
require a secure context (HTTPS, or `localhost`), and a phone reaching the
laptop over `http://192.168.x.x` on your LAN doesn't qualify — that's just
how browsers treat plain HTTP off-device. The manual "Add to Home screen"
route still gets you the same app-like icon and standalone window, it's
just a menu tap instead of an automatic prompt.

## Using it from n8n

The container also runs a small HTTP API on port `8080`, reachable from
anywhere on your local network (see [Web UI & monitoring from your
phone](#web-ui--monitoring-from-your-phone) above) — see the note below if
n8n itself runs in Docker.

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
is a plain liveness check. `POST /drafts` (body: `to`, `subject`, `body`,
optional `business_name`/`pitch`) appends a record to `data/drafts.jsonl` —
useful as a local, no-Google-account-needed place to land generated emails
for review before wiring up real sending; `GET /drafts` reads them back.

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

## Email lookup

Google Maps doesn't expose business emails, so when `SCRAPE_EMAILS=true`
(on by default in `docker-compose.yml`) the scraper opens each business's
own `website` in a separate tab and looks for a `mailto:` link, falling
back to scanning the page (and a couple of common `/contact` paths) for an
email-shaped string. It's best-effort — some sites won't have a findable
one and `email` will just come back empty — and adds real time per
business, so turn it off (`SCRAPE_EMAILS=false`) if you don't need it.

## AI-drafted outreach

When `GENERATE_PITCHES=true` (on by default in `docker-compose.yml`) and a
business has an email, the scraper calls a locally-running
[Ollama](https://ollama.com) model right after scraping it — no cloud LLM,
no API key. It reads the business's category, rating, and actual review
text, decides which of two pitches fits better, and writes a short,
specific email referencing something real about that business (not a mass
template). Every draft is appended to `data/drafts.jsonl` — nothing is
sent automatically.

Requirements: Ollama running on the same machine (`ollama serve`, with a
model pulled — `OLLAMA_MODEL` defaults to `gemma3:12b`). The scraper reaches
it at `OLLAMA_URL` (defaults to `http://host.docker.internal:11434`, which
resolves to the host machine from inside the container).

**Before sending anything for real**, set `COMPANY_ADDRESS` to your actual
business address — commercial email conventionally requires one, and the
default is a placeholder (`[YOUR BUSINESS ADDRESS HERE]`) that will
otherwise go out literally as written. Review `data/drafts.jsonl` (or the
web UI) before wiring up real sending.

**Other outreach channels** (LinkedIn DMs, SMS/phone, WhatsApp) aren't
built — each has its own account setup, cost, and ban/compliance risk
significantly different from email, worth deciding on deliberately rather
than bolting on by default.

## Configuration

Set these as environment variables (see `docker-compose.yml`):

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `30` | How often to check `queries.yaml` for new work |
| `DELAY_BETWEEN_QUERIES_MIN` / `_MAX` | `20` / `60` | Random pause between queries, in seconds |
| `REVIEWS_PER_BUSINESS` | `5` | Max recent reviews to capture per business |
| `SKIP_ALREADY_SEEN` | `true` | Skip businesses already captured in a previous run |
| `SCRAPE_EMAILS` | `false` (`true` in `docker-compose.yml`) | Visit each business's website and try to find a contact email |
| `EMAIL_FETCH_TIMEOUT_MS` | `12000` | Timeout for the email lookup per website |
| `GENERATE_PITCHES` | `false` (`true` in `docker-compose.yml`) | Call local Ollama to draft an outreach email when an email was found |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Where the scraper reaches your local Ollama server |
| `OLLAMA_MODEL` | `gemma3:12b` | Which pulled Ollama model to use for drafting |
| `OLLAMA_TIMEOUT_S` | `120` | Timeout per draft (covers Ollama's cold-start model load) |
| `COMPANY_ADDRESS` | `[YOUR BUSINESS ADDRESS HERE]` | Appended to every draft's footer — set this before sending anything real |
| `DEFAULT_MAX_RESULTS` | `60` | Used when a query entry doesn't set `max_results` |
| `HEADLESS` | `true` | Set to `false` to run Chromium with a visible window (needs a display) |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `API_PORT` | `8080` | Port the HTTP API and web UI listen on |

## Project layout

```
Dockerfile / docker-compose.yml   container + Chromium setup
pyproject.toml / setup.sh / setup.ps1 / run.sh / run.ps1   native (no-Docker) setup, via uv
data/queries.yaml                 the job queue (mounted volume)
data/results/                     CSV/JSON output (mounted volume)
data/drafts.jsonl                 generated outreach emails, for review
src/main.py                       entrypoint: starts the API + worker thread
src/api.py                        HTTP API (FastAPI): POST /scrape, GET /jobs/{id}, /drafts; serves the web UI
src/web/index.html                the web UI (single static page, no build step)
src/web/manifest.json, sw.js, icons/   makes the web UI installable as an app (PWA)
src/jobs.py                       in-memory job store shared by the API and worker
src/queue_runner.py               worker loop: drains API jobs, then queries.yaml
src/maps_scraper.py               Playwright scraping logic
src/email_finder.py               best-effort contact-email lookup from a business's website
src/pitch_writer.py               calls local Ollama to draft a personalized outreach email
src/drafts_store.py               appends/reads generated drafts to/from data/drafts.jsonl
src/live_view.py                  holds the latest screenshot, served at GET /live
src/seen_store.py                 place-ID dedup, persisted to data/seen_places.txt
src/exporter.py                   CSV/JSON writers
src/models.py                     Business/Review data model
src/config.py                     environment variable settings
```
