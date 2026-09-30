const { app, BrowserWindow, shell, Menu, ipcMain, dialog, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const { spawn } = require('child_process');

// Two ways to run:
//  - "local":  this machine runs the scraper (and talks to Ollama on this
//              machine). Packaged builds carry the backend inside the app;
//              running from the repo (npm start) uses Docker or uv as before.
//  - "remote": monitor-only window over a server that's already running
//              somewhere else (Docker box, another PC, ...).
// The choice is remembered; Ctrl/Cmd+Shift+M reopens the chooser.

const IS_PACKAGED = app.isPackaged;
const REPO_ROOT = path.resolve(__dirname, '..');
const APP_PORT = process.env.API_PORT || '8080';
const LOCAL_URL = `http://localhost:${APP_PORT}`;
const OLLAMA_URL = process.env.OLLAMA_URL_LOCAL || 'http://localhost:11434';
const ICON_PATH = IS_PACKAGED
  ? path.join(process.resourcesPath, 'backend', 'src', 'web', 'icons', 'icon-512.png')
  : path.join(REPO_ROOT, 'src', 'web', 'icons', 'icon-512.png');
const PRELOAD_PATH = path.join(__dirname, 'preload.js');

let mainWindow = null;
let backendChild = null;
let appUrl = LOCAL_URL;
let tokenFile = path.join(REPO_ROOT, 'data', '.auth_token');
let remoteToken = null;

// ---------- settings ----------

function configPath() {
  return path.join(app.getPath('userData'), 'gyraq-app.json');
}

function loadConfig() {
  try {
    const cfg = JSON.parse(fs.readFileSync(configPath(), 'utf8'));
    if (cfg.token_enc) {
      cfg.token = safeStorage.isEncryptionAvailable()
        ? safeStorage.decryptString(Buffer.from(cfg.token_enc, 'base64'))
        : null;
    }
    return cfg;
  } catch {
    return {};
  }
}

function saveConfig(cfg) {
  const out = { mode: cfg.mode, url: cfg.url || null };
  if (cfg.token) {
    if (safeStorage.isEncryptionAvailable()) {
      out.token_enc = safeStorage.encryptString(cfg.token).toString('base64');
    } else {
      out.token = cfg.token;
    }
  }
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(out), { mode: 0o600 });
}

// ---------- helpers ----------

function readAuthToken() {
  if (remoteToken) return remoteToken;
  try {
    return fs.readFileSync(tokenFile, 'utf8').trim() || null;
  } catch {
    return null;
  }
}

function getLanIp() {
  const nets = os.networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name] || []) {
      const isV4 = typeof net.family === 'string' ? net.family === 'IPv4' : net.family === 4;
      if (isV4 && !net.internal) return net.address;
    }
  }
  return null;
}

ipcMain.handle('get-lan-url', () => {
  if (appUrl !== LOCAL_URL) return appUrl;
  const ip = getLanIp();
  return ip ? `http://${ip}:${APP_PORT}` : null;
});

function httpOk(url, timeout = 2000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout }, (res) => {
      resolve(res.statusCode === 200);
      res.resume();
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

const checkHealth = (base = appUrl) => httpOk(`${base}/health`);

function commandExists(cmd) {
  return new Promise((resolve) => {
    const checker = process.platform === 'win32' ? spawn('where', [cmd]) : spawn('which', [cmd]);
    checker.on('close', (code) => resolve(code === 0));
    checker.on('error', () => resolve(false));
  });
}

async function waitForHealth(maxWaitMs) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (await checkHealth()) return true;
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

function pageHtml(body) {
  return (
    'data:text/html,' +
    encodeURIComponent(`<html><body style="margin:0;display:flex;align-items:center;justify-content:center;
      min-height:100vh;background:#0f1115;color:#e6e8ec;font-family:-apple-system,Segoe UI,sans-serif;">
      <div style="text-align:center;max-width:420px;padding:16px">${body}</div></body></html>`)
  );
}

function attachShortcuts(win) {
  // No application menu, so wire Reload/DevTools/"switch mode" by hand.
  win.webContents.on('before-input-event', (_event, input) => {
    if (input.type !== 'keyDown') return;
    const mod = input.control || input.meta;
    const key = input.key.toLowerCase();
    if (mod && input.shift && key === 'm') {
      resetModeAndRestart();
    } else if (mod && key === 'r') {
      win.webContents.reloadIgnoringCache();
    } else if (input.key === 'F12' || (mod && input.shift && key === 'i')) {
      win.webContents.toggleDevTools();
    }
  });
}

function resetModeAndRestart() {
  try {
    fs.unlinkSync(configPath());
  } catch {}
  app.relaunch();
  app.quit();
}

// ---------- mode chooser ----------

let chooserResolve = null;

ipcMain.handle('choose-mode', (_e, choice) => {
  if (!choice || (choice.mode !== 'local' && choice.mode !== 'remote')) return { ok: false };
  if (choice.mode === 'remote') {
    try {
      const u = new URL(choice.url);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('bad protocol');
      choice.url = u.origin;
    } catch {
      return { ok: false, error: 'Enter a full server address, e.g. http://192.168.1.20:8080' };
    }
  }
  if (chooserResolve) chooserResolve(choice);
  return { ok: true };
});

function chooseMode() {
  return new Promise((resolve) => {
    const win = new BrowserWindow({
      width: 640,
      height: 560,
      resizable: false,
      backgroundColor: '#0f1115',
      title: 'Gyraq Lead Scraper',
      icon: ICON_PATH,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: PRELOAD_PATH },
    });
    win.removeMenu();
    chooserResolve = (choice) => {
      chooserResolve = null;
      win.removeAllListeners('closed');
      win.close();
      resolve(choice);
    };
    win.on('closed', () => {
      if (chooserResolve) app.quit();
    });
    win.loadFile(path.join(__dirname, 'chooser.html'));
  });
}

// ---------- local backend ----------

function resourcePaths() {
  const backend = IS_PACKAGED ? path.join(process.resourcesPath, 'backend') : REPO_ROOT;
  const uvName = process.platform === 'win32' ? 'uv.exe' : 'uv';
  const bundledUv = path.join(process.resourcesPath || '', 'uv', uvName);
  return { backend, uv: IS_PACKAGED && fs.existsSync(bundledUv) ? bundledUv : 'uv' };
}

function run(cmd, args, opts) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, opts);
    child.on('close', (code) => resolve(code));
    child.on('error', () => resolve(-1));
  });
}

async function startPackagedBackend(setStatus) {
  const { backend, uv } = resourcePaths();
  const userData = app.getPath('userData');
  const dataDir = path.join(userData, 'data');
  fs.mkdirSync(path.join(dataDir, 'results'), { recursive: true });
  tokenFile = path.join(dataDir, '.auth_token');

  const queries = path.join(dataDir, 'queries.yaml');
  const template = path.join(backend, 'queries.yaml');
  if (!fs.existsSync(queries) && fs.existsSync(template)) fs.copyFileSync(template, queries);

  const logFd = fs.openSync(path.join(userData, 'backend.log'), 'a');
  const env = {
    ...process.env,
    PYTHONDONTWRITEBYTECODE: '1',
    UV_PROJECT_ENVIRONMENT: path.join(userData, 'venv'),
    PLAYWRIGHT_BROWSERS_PATH: path.join(userData, 'browsers'),
    QUERIES_FILE: queries,
    RESULTS_DIR: path.join(dataDir, 'results'),
    SEEN_STORE_FILE: path.join(dataDir, 'seen_places.txt'),
    DB_FILE: path.join(dataDir, 'app.db'),
    API_PORT: APP_PORT,
    OLLAMA_URL,
    SCRAPE_EMAILS: process.env.SCRAPE_EMAILS || 'true',
    GENERATE_PITCHES: process.env.GENERATE_PITCHES || 'true',
    RESEARCH_REPUTATION: process.env.RESEARCH_REPUTATION || 'true',
    HEADLESS: 'true',
  };
  const opts = { cwd: backend, env, stdio: ['ignore', logFd, logFd], windowsHide: true };

  setStatus('Installing Python packages (first launch only)…');
  let code = await run(uv, ['sync', '--project', backend, '--frozen'], opts);
  if (code !== 0) return false;

  const browsersMarker = path.join(userData, 'browsers', '.installed');
  if (!fs.existsSync(browsersMarker)) {
    setStatus('Downloading Chromium (first launch only, ~150 MB)…');
    code = await run(uv, ['run', '--project', backend, '--frozen', 'playwright', 'install', 'chromium'], opts);
    if (code !== 0) return false;
    fs.writeFileSync(browsersMarker, '');
  }

  setStatus('Starting scraper…');
  backendChild = spawn(uv, ['run', '--project', backend, '--frozen', 'python', '-m', 'src.main'], {
    ...opts,
    detached: process.platform !== 'win32',
  });
  backendChild.on('close', () => {
    backendChild = null;
  });
  return true;
}

async function startRepoBackend(setStatus) {
  // Running from a checkout (npm start): same behaviour as before.
  if (await commandExists('docker')) {
    setStatus('Starting backend via Docker Compose…');
    await run('docker', ['compose', 'up', '-d', '--build'], { cwd: REPO_ROOT, stdio: 'inherit' });
    return true;
  }
  setStatus('Docker not found - starting natively via uv…');
  const isWin = process.platform === 'win32';
  const child = spawn(
    isWin ? 'powershell.exe' : 'bash',
    isWin ? ['-ExecutionPolicy', 'Bypass', '-File', 'run.ps1'] : ['run.sh'],
    { cwd: REPO_ROOT, detached: !isWin, stdio: 'ignore' }
  );
  child.unref();
  return true;
}

function stopBackend() {
  if (!backendChild) return;
  const pid = backendChild.pid;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F']);
    } else {
      process.kill(-pid, 'SIGTERM');
    }
  } catch {}
  backendChild = null;
}

async function warnIfNoOllama() {
  if (await httpOk(`${OLLAMA_URL}/api/tags`)) return;
  const { response } = await dialog.showMessageBox({
    type: 'info',
    title: 'Ollama not found',
    message: 'Ollama isn\'t running on this computer.',
    detail:
      'Scraping works without it, but AI-drafted pitches and the WhatsApp chatbot need Ollama. ' +
      'Install it, then run:\n  ollama pull gemma3:12b\n  ollama pull qwen3:8b',
    buttons: ['Get Ollama', 'Continue without'],
    defaultId: 1,
  });
  if (response === 0) shell.openExternal('https://ollama.com/download');
}

// ---------- windows ----------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 850,
    backgroundColor: '#0f1115',
    title: 'Gyraq Lead Scraper',
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: PRELOAD_PATH,
    },
  });

  // The backend requires a token on every API call (see src/auth.py). For a
  // local backend it's read off disk; for a remote one it's whatever the
  // user entered in the chooser (or they sign in through the page itself).
  const token = readAuthToken();
  if (token) {
    mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
      { urls: [`${appUrl}/*`] },
      (details, callback) => {
        details.requestHeaders['X-App-Token'] = token;
        callback({ requestHeaders: details.requestHeaders });
      }
    );
  }

  mainWindow.loadURL(appUrl);
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  attachShortcuts(mainWindow);
}

function showError(html) {
  const win = new BrowserWindow({ width: 560, height: 320, icon: ICON_PATH });
  win.removeMenu();
  win.loadURL(pageHtml(html));
  attachShortcuts(win);
}

function setupAutoUpdate() {
  if (!IS_PACKAGED) return;
  try {
    const { autoUpdater } = require('electron-updater');
    autoUpdater.on('error', (e) => console.warn('[gyraq] update check failed:', e && e.message));
    autoUpdater.checkForUpdatesAndNotify();
    setInterval(() => autoUpdater.checkForUpdatesAndNotify().catch(() => {}), 6 * 60 * 60 * 1000);
  } catch (e) {
    console.warn('[gyraq] auto-update unavailable:', e.message);
  }
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);

  let cfg = loadConfig();
  if (!cfg.mode) {
    cfg = await chooseMode();
    saveConfig(cfg);
  }

  if (cfg.mode === 'remote') {
    appUrl = cfg.url;
    remoteToken = cfg.token || null;
    if (await checkHealth(appUrl).then((ok) => ok || checkHealth(appUrl))) {
      createWindow();
    } else {
      showError(`<h3>Can't reach ${appUrl}</h3>
        <p>Check the server is running and this computer can reach it.<br>
        Press Ctrl/Cmd+Shift+M to change the server or switch to running it here.</p>`);
    }
    setupAutoUpdate();
    return;
  }

  appUrl = LOCAL_URL;
  if (await checkHealth()) {
    createWindow();
    setupAutoUpdate();
    return;
  }

  const loading = new BrowserWindow({
    width: 440,
    height: 220,
    resizable: false,
    title: 'Gyraq Lead Scraper',
    icon: ICON_PATH,
  });
  loading.removeMenu();
  loading.loadURL(
    pageHtml(`<div style="font-size:16px;font-weight:600;margin-bottom:8px">Starting Gyraq Lead Scraper…</div>
      <div id="s" style="font-size:12px;color:#8b909c">Preparing…</div>`)
  );
  const setStatus = (text) => {
    if (loading.isDestroyed()) return;
    loading.webContents
      .executeJavaScript(`document.getElementById('s').textContent = ${JSON.stringify(text)}`)
      .catch(() => {});
  };

  const started = IS_PACKAGED ? await startPackagedBackend(setStatus) : await startRepoBackend(setStatus);
  const ok = started && (await waitForHealth(120000));
  loading.close();

  if (ok) {
    createWindow();
    warnIfNoOllama();
  } else {
    const where = IS_PACKAGED ? `Details are in <code>${path.join(app.getPath('userData'), 'backend.log')}</code>.` : 'Try <code>docker compose up -d --build</code> or <code>./run.sh</code> in the repo folder.';
    showError(`<h3>Couldn't start the scraper</h3><p>${where}<br>
      Press Ctrl/Cmd+Shift+M to switch to monitoring a server instead.</p>`);
  }
  setupAutoUpdate();
});

app.on('before-quit', stopBackend);

app.on('window-all-closed', () => {
  // A checkout-launched backend (Docker / detached process) is an always-on
  // service, but a packaged app owns its backend, so that stops with the app.
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (app.isReady() && BrowserWindow.getAllWindows().length === 0 && appUrl) createWindow();
});
