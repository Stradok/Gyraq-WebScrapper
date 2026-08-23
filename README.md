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
identically on Windows, macOS, and Linux; [uv](https://docs.astral.sh/uv/)
is a single cross-platform binary that handles the Python install, virtual
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

## Option C: Desktop app window (Electron)

A thin wrapper around whichever of the two options above you use — instead
of opening `localhost:8080` in a browser tab, you get a real app window
(its own taskbar/dock entry, no address bar). It doesn't reimplement
anything: on launch it checks if the backend is already up, and if not,
starts it the same way you would by hand (`docker compose up -d --build`
if Docker is available, otherwise the native `run.sh`/`run.ps1` path) and
waits for it before opening the window.

Requires [Node.js](https://nodejs.org) on the machine you're launching
from (only for running it this way — it's not needed by Docker or the
native `uv` path).

```bash
git clone https://github.com/Stradok/Gyraq-WebScrapper.git
cd Gyraq-WebScrapper
npm run app:setup   # one-time: installs Electron itself
npm run app         # launches the window (starts the backend if needed)
```

First launch can take a minute if the backend also needs to build/start —
you'll see a small "Starting…" window while that happens. Closing the app
window does **not** stop the backend (it's meant to stay running as a
service, same as the other two options) — closing is just closing the
window, same as closing a browser tab, the container/process keeps going.

This currently runs from source (`npm run app`) rather than as a
double-click installer (`.exe`/`.dmg`/`.AppImage`) — packaging that with
`electron-builder` is a reasonable next step if you want a one-click
launcher without Node.js installed, but wasn't built yet since it needs
testing on each target OS to get right.

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

**Easiest**: on the laptop, sign in to the web UI and open the
**Remote access** panel (in the "Jump to…" nav dropdown, top right) — scan
the QR code with your phone's camera and it opens the app already signed
in, no typing.

**Manually**, if you'd rather not scan:

1. Find the laptop's local network IP:
   - **Windows**: `ipconfig` → look for "IPv4 Address" (something like `192.168.1.42`)
   - **Linux**: `hostname -I` or `ip addr`
   - **macOS**: `ipconfig getifaddr en0` (or System Settings → Wi-Fi → Details)
2. On your phone's browser, go to `http://<that-ip>:8080` — e.g. `http://192.168.1.42:8080`.
3. Paste in the access token when prompted (see [Security](#security) for
   where to find it).

The port is published on all network interfaces, not just `localhost` —
which means anything else on the same WiFi can *reach* it, but the access
token (see [Security](#security)) stops them from actually doing anything
without it. For extra peace of mind on a shared network, put it behind
your router's firewall rules or a VPN instead of exposing it further.

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

### Monitoring from anywhere, not just the same WiFi

The steps above only work while your phone is on the same network as the
laptop. To check on it from actual cellular data / a different WiFi
(coffee shop, out and about), you need the laptop reachable over the
internet — and the responsible way to do that is **not** router port
forwarding. The access token (see [Security](#security)) helps, but plain
HTTP port-forwarded to the open internet is still a bad idea — no
encryption in transit, and the token can end up in browser history, proxy
logs, etc. along the way.

Use [Tailscale](https://tailscale.com) instead (free for personal use):

1. Install it on the laptop and sign in.
2. Install the Tailscale app on your phone and sign in with the **same
   account**.
3. Tailscale gives the laptop a private address (something like
   `100.x.y.z`, or a name like `laptop-name.tailnet-name.ts.net`) — visible
   in the Tailscale app/admin console.
4. From your phone, anywhere with internet, go to
   `http://<that-tailscale-address>:8080`.

No app changes, no port forwarding, no public exposure — Tailscale creates
a private encrypted network between just your own devices, so from this
app's perspective your phone looks like it's on the same LAN as the laptop
even when it's on the other side of the world. If you'd rather not install
anything extra and just want a quick one-off peek, a tunneling tool like
`ngrok` also works, but its free tier gives a new public URL each restart
and — unlike Tailscale — that URL is reachable by anyone who has it, not
just your own devices.

## Security

The API and web UI are reachable from anywhere on your local network (see
above) with no login by default — that would mean anyone on the same WiFi
could read your scraped leads, reconfigure your mail/WhatsApp credentials,
or trigger sends. To close that off, **every route except `/health` and the
page shell itself requires a token**, checked via an `X-App-Token` header.

- The token is generated once, automatically, on first run — no setup step.
- Find it three ways: the **Remote access** panel in the web UI once you're
  signed in on one device, the container's startup logs (`docker compose
  logs`), or the file `data/.auth_token` directly.
- The **desktop app** (Electron) reads the token straight off disk and
  attaches it to every request automatically — zero manual steps for that,
  the primary way of using this.
- A plain browser (including at `localhost:8080`) needs the token pasted in
  once; it's then remembered for that browser via local storage.
- **Anything that calls the API programmatically — n8n, curl, a script —
  needs to send the token too**, or every call gets a `401`. See below.

Other hardening worth knowing about:
- `data/app.db` (holds mail/WhatsApp credentials) is created with
  owner-only file permissions (`600`).
- The WhatsApp webhook verifies Meta's `X-Hub-Signature-256` HMAC when an
  **App secret** is configured (Connections → WhatsApp) — without it,
  anyone who discovers your tunnel URL could inject fake "incoming
  messages"; with it, forged payloads are rejected with `403`.
- The Electron window runs with `contextIsolation`, no `nodeIntegration`,
  and Chromium's OS-level sandbox enabled — a compromised page it loads
  (or one it opens externally via a link) can't reach your filesystem or
  Node APIs.
- Credentials (mail/WhatsApp) are stored locally in plain text — there's no
  clean way to encrypt secrets at rest for a single-user local app without
  either an OS keychain integration (not built) or a master password you'd
  have to re-enter constantly (fights the "smooth" goal). File permissions
  plus the access token are the practical boundary here, not encryption.

## Using it from n8n

The container also runs a small HTTP API on port `8080`, reachable from
anywhere on your local network (see [Web UI & monitoring from your
phone](#web-ui--monitoring-from-your-phone) above) — see the note below if
n8n itself runs in Docker.

**Every request below needs the access token** (see
[Security](#security)) as an `X-App-Token` header — grab it from
`data/.auth_token` or the container logs.

**1. Start a scrape** — `POST` a query, get back a job id immediately:

```bash
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -H "X-App-Token: <your token>" \
  -d '{"query": "gyms in Chicago, IL", "max_results": 20}'
```
```json
{"job_id": "fec0c255a123", "status": "queued", ...}
```

**2. Poll for the result** — scrapes take anywhere from a few seconds to a
few minutes depending on `max_results`, so poll until `status` is `done` (or
`error`):

```bash
curl -H "X-App-Token: <your token>" http://localhost:8080/jobs/fec0c255a123
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

**In n8n**, this is two HTTP Request nodes — on **both**, add a header
`X-App-Token: <your token>` (in the node's Headers section):

- **HTTP Request** (POST) → `http://localhost:8080/scrape`, JSON body
  `{"query": "...", "max_results": ...}` → returns `job_id`.
- **HTTP Request** (GET) → `http://localhost:8080/jobs/{{ $json.job_id }}`,
  wired into a **Wait** node + loop (or the "retry on fail" option) until
  `status` isn't `queued`/`running` — then the `results` array is ready to
  feed into the rest of the workflow.

If you built this workflow before the access token existed, add that
header to each HTTP Request node now — they'll otherwise start getting
`401 unauthorized` after updating.

Other endpoints: `GET /jobs` lists every job with its status, `GET /health`
is a plain liveness check. `POST /drafts` (body: `to`, `subject`, `body`,
optional `business_name`/`pitch`) saves a record to the local database —
useful as a place to land generated emails for review before sending;
`GET /drafts` reads them back. See [Sending email &
WhatsApp](#sending-email--whatsapp) below for actually sending them.

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
no API key. It reads the business's category, rating, review text, and
review count, then picks **one** of four angles based on what it actually
has evidence for:

- **Website** — no website, or a very basic one
- **Voice agent** — reviews/research mention missed calls, slow replies, long waits
- **Automation** — mentions of manual scheduling problems, missed follow-ups, no online booking
- **Lead generation** — low review count / limited visibility, would benefit from more customer volume

It writes a short, specific email referencing something real about that
business (not a mass template). Every draft is saved to the local
database — nothing is sent automatically; review and send it from the web
UI's **Drafted emails** panel (checkboxes + **Send selected** / **Send all
pending**), which uses whatever you've configured under **Connections →
Email** below.

Requirements: Ollama running on the same machine (`ollama serve`, with a
model pulled — `OLLAMA_MODEL` defaults to `gemma3:12b`). The scraper reaches
it at `OLLAMA_URL` (defaults to `http://host.docker.internal:11434`, which
resolves to the host machine from inside the container).

**Before sending anything for real**, set `COMPANY_ADDRESS` to your actual
business address — commercial email conventionally requires one, and the
default is a placeholder (`[YOUR BUSINESS ADDRESS HERE]`) that will
otherwise go out literally as written.

### Reddit & review research

When `RESEARCH_REPUTATION=true` (on by default in `docker-compose.yml`),
before drafting each pitch the scraper also searches the web (via
DuckDuckGo's HTML results — no API key) for the business's name plus
"reddit" and separately plus "reviews complaints", and hands whatever it
finds to the model alongside the Google review text.

This changes what the email leads with:

- **Found a real, specific complaint** (a Reddit thread or a review-site
  mention of missed calls, long waits, no website, etc.) — the model cites
  it directly as evidence: *"I noticed on Yelp that [business] often has
  long wait times on weekends..."* This is the strongest version of the
  email, grounded in something a stranger can independently verify.
- **Found only positive/neutral mentions, or nothing at all** — the model
  is explicitly instructed not to fabricate a complaint or twist a good
  review into a fake one. It falls back to a specific, confident pitch
  grounded in a real fact it does have (no website, their category's
  common pain points) — still a strong, non-generic email, just without a
  cited complaint.

Verified directly: fed the same business real Yelp/Reddit search results
with one genuine complaint mixed with several positive mentions — the
model correctly cited only the real complaint and ignored the positive
ones rather than inventing something from them; with no complaint
available at all, it wrote a specific pitch based on the business having
no website rather than a generic template.

This adds real time per business (two more page loads) and is another
site being scraped in a way its terms likely don't invite, same caveat as
the rest of this project — turn it off with `RESEARCH_REPUTATION=false` if
you don't want it.

**LinkedIn DMs and SMS/phone outreach** aren't built — each has its own
account setup, cost, and ban/compliance risk significantly different from
email and WhatsApp, worth deciding on deliberately rather than bolting on
by default.

## Sending email & WhatsApp

The web UI has a **Connections** panel with two tabs for wiring up real
sending — no code or `.env` editing needed, it's all saved to the local
database from the browser.

### Email (SMTP to send, IMAP to receive)

Click a provider preset (**Gmail**, **Outlook/Office365**, or **Custom**)
to prefill the host/port, fill in your address and password, hit **Save**,
then **Test SMTP** to confirm it can actually send. IMAP is optional —
only needed if you want the app to read incoming replies later.

For Gmail/Outlook, use an **app password**, not your normal login
password — both providers require this for third-party apps once 2-factor
auth is on (Google: Account → Security → App Passwords; Microsoft:
similar under Security → Advanced security options). Passwords are stored
locally in `data/app.db`, in plain text — this is a local single-user
tool, not a hosted service, but don't commit or share that file.

### WhatsApp (official Business Cloud API)

This uses Meta's official platform, not an unofficial/ToS-violating
automation library — no ban risk to a personal number, but real setup on
Meta's side:

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps),
   create an app (type: **Business**), and add the **WhatsApp** product.
2. Under WhatsApp → **API Setup**, Meta gives you a free test phone number,
   a **Phone Number ID**, and a temporary (24h) access token — enough to
   try everything below before doing full business verification for a
   permanent token and your own number.
3. In this app's **Connections → WhatsApp** tab, paste the **Access
   token** and **Phone number ID**, then **Save** and **Test connection**.
4. Pick any string as your **Webhook verify token** (just a shared secret
   you invent) and save it too — the UI shows you the exact webhook URL
   to use in the next step.
5. **To receive incoming messages**, Meta needs to reach your webhook over
   the public internet — `localhost` or your LAN IP won't work, Meta's
   servers aren't on your network. Use a tunnel like
   [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
   (free, stable URL) or [ngrok](https://ngrok.com/) (free, URL changes on
   restart unless paid) to get a public HTTPS URL pointing at this app's
   port, then in Meta's app dashboard → WhatsApp → **Configuration** →
   Webhook, enter `https://<your-tunnel-url>/webhooks/whatsapp`, the same
   verify token from step 4, and subscribe to the `messages` field.
6. **Also set the App secret** (Connections → WhatsApp, found on your
   app's dashboard under Settings → Basic) once you're tunneling publicly
   — without it, anyone who finds your tunnel URL could POST fake
   "incoming messages"; with it, every webhook call is verified against
   Meta's signature and forged ones are rejected.

One WhatsApp platform rule, not a limitation of this code: you can only
send free-form text as a **reply** within 24 hours of the customer's last
message. Starting a fresh conversation (cold outreach) requires a
Meta-approved message *template* — template creation/approval isn't built
yet, since it only matters once you're past the receiving/replying setup
above.

Incoming WhatsApp messages are currently recorded (`GET /whatsapp/inbox`)
but not auto-replied to — the auto-reply logic (what to say, staying
within FAQ/info-collection bounds, never quoting prices) is a deliberate
next step, not built silently alongside the plumbing.

## Data viewer & stats

The web UI's **Overview** row shows running totals (searches completed,
businesses scraped, drafts pending/sent/failed) pulled live from the
database — also available as JSON at `GET /stats`.

The **Scraped data** panel lists every result file from `data/results/`
by query and count; click one to load it into a table (name, category,
rating, reviews, address, phone, email, website) right in the browser,
instead of opening the JSON/CSV by hand. Backed by `GET /results` (list)
and `GET /results/{filename}` (one file's full data).

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
| `RESEARCH_REPUTATION` | `false` (`true` in `docker-compose.yml`) | Search Reddit/review sites for real complaints to ground pitches in |
| `REPUTATION_TIMEOUT_MS` | `15000` | Timeout for each reputation search |
| `DEFAULT_MAX_RESULTS` | `60` | Used when a query entry doesn't set `max_results` |
| `HEADLESS` | `true` | Set to `false` to run Chromium with a visible window (needs a display) |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `API_PORT` | `8080` | Port the HTTP API and web UI listen on |
| `DB_FILE` | `data/app.db` | SQLite database: job history, drafts, mail/WhatsApp settings |

Mail and WhatsApp credentials are *not* environment variables — set those
from the web UI's Connections panel (see above), they're saved to `DB_FILE`.

## Project layout

```
Dockerfile / docker-compose.yml   container + Chromium setup
pyproject.toml / setup.sh / setup.ps1 / run.sh / run.ps1   native (no-Docker) setup, via uv
electron/main.js, preload.js      desktop app shell: backend auto-start, LAN IP, auto-injects the access token
data/queries.yaml                 the job queue (mounted volume)
data/results/                     CSV/JSON output (mounted volume)
data/app.db                       SQLite: job history, drafts, mail/WhatsApp settings (owner-only permissions)
data/.auth_token                  the access token, plain file, owner-only permissions
src/main.py                       entrypoint: starts the API + worker thread
src/api.py                        HTTP API (FastAPI): all routes below + the auth middleware, serves the web UI
src/auth.py                       generates/verifies the access token
src/qr.py                         generates the QR PNG for the Remote Access panel
src/web/index.html                the web UI (single static page, no build step)
src/web/manifest.json, sw.js, icons/   makes the web UI installable as an app (PWA)
src/db.py                         SQLite connection + schema (self-initializing)
src/jobs.py                       persistent job store shared by the API and worker
src/queue_runner.py               worker loop: drains API jobs, then queries.yaml
src/maps_scraper.py               Playwright scraping logic
src/email_finder.py               best-effort contact-email lookup from a business's website
src/pitch_writer.py               calls local Ollama to draft a personalized outreach email
src/reputation_finder.py          searches Reddit/review sites for real complaints about a business
src/drafts_store.py               drafts CRUD (pending/sent/failed) against the database
src/mail_settings.py              SMTP/IMAP credentials CRUD against the database
src/mailer.py                     actually sends via smtplib; IMAP connectivity test
src/whatsapp_settings.py          WhatsApp Cloud API credentials CRUD against the database
src/whatsapp.py                   Meta Graph API client; webhook payload parsing
src/results_store.py              lists/reads data/results/*.json for the data viewer
src/stats.py                      aggregate counts for the Overview panel
src/live_view.py                  holds the latest screenshot, served at GET /live
src/seen_store.py                 place-ID dedup, persisted to data/seen_places.txt
src/exporter.py                   CSV/JSON writers
src/models.py                     Business/Review data model
src/config.py                     environment variable settings
```
