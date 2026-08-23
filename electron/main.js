const { app, BrowserWindow, shell, Menu, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const { spawn } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const APP_PORT = process.env.API_PORT || '8080';
const APP_URL = `http://localhost:${APP_PORT}`;
const HEALTH_URL = `${APP_URL}/health`;
const ICON_PATH = path.join(REPO_ROOT, 'src', 'web', 'icons', 'icon-512.png');
const PRELOAD_PATH = path.join(__dirname, 'preload.js');
const TOKEN_FILE = path.join(REPO_ROOT, 'data', '.auth_token');

let mainWindow = null;

function readAuthToken() {
  try {
    return fs.readFileSync(TOKEN_FILE, 'utf8').trim() || null;
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
  const ip = getLanIp();
  return ip ? `http://${ip}:${APP_PORT}` : null;
});

function checkHealth() {
  return new Promise((resolve) => {
    const req = http.get(HEALTH_URL, { timeout: 2000 }, (res) => {
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

function commandExists(cmd) {
  return new Promise((resolve) => {
    const checker =
      process.platform === 'win32' ? spawn('where', [cmd]) : spawn('which', [cmd]);
    checker.on('close', (code) => resolve(code === 0));
    checker.on('error', () => resolve(false));
  });
}

async function startBackend() {
  const hasDocker = await commandExists('docker');
  if (hasDocker) {
    console.log('[gyraq] Starting backend via Docker Compose...');
    await new Promise((resolve) => {
      const child = spawn('docker', ['compose', 'up', '-d', '--build'], {
        cwd: REPO_ROOT,
        stdio: 'inherit',
      });
      child.on('close', resolve);
      child.on('error', resolve);
    });
    return;
  }

  console.log('[gyraq] Docker not found - starting backend natively via uv...');
  const isWin = process.platform === 'win32';
  const child = spawn(
    isWin ? 'powershell.exe' : 'bash',
    isWin ? ['-ExecutionPolicy', 'Bypass', '-File', 'run.ps1'] : ['run.sh'],
    {
      cwd: REPO_ROOT,
      detached: !isWin,
      stdio: 'ignore',
    }
  );
  child.unref();
}

async function waitForHealth(maxWaitMs) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (await checkHealth()) return true;
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

function loadingHtml() {
  return (
    'data:text/html,' +
    encodeURIComponent(`
    <html><body style="margin:0;display:flex;align-items:center;justify-content:center;
      height:100vh;background:#0f1115;color:#e6e8ec;font-family:-apple-system,sans-serif;">
      <div style="text-align:center;max-width:320px">
        <div style="font-size:16px;font-weight:600;margin-bottom:8px;">Starting Gyraq Lead Scraper…</div>
        <div style="font-size:12px;color:#8b909c;">First launch can take a minute (building the container / installing Chromium).</div>
      </div>
    </body></html>
  `)
  );
}

function errorHtml() {
  return (
    'data:text/html,' +
    encodeURIComponent(`
    <body style="font-family:-apple-system,sans-serif;padding:24px;background:#0f1115;color:#e6e8ec;">
      <h3>Couldn't start the backend</h3>
      <p>Tried Docker and the native (uv) path but neither came up within 2 minutes.
      Check Docker Desktop is running, or try <code>docker compose up -d --build</code>
      (or <code>./run.sh</code> / <code>.\\run.ps1</code>) manually in the repo folder,
      then reopen this app.</p>
    </body>
  `)
  );
}

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

  // The backend requires a token on every API call (see src/auth.py) -
  // since this app runs on the same machine as the backend, read it
  // straight off disk and attach it to every request automatically so
  // there's zero manual setup for this, the primary way of using the app.
  const token = readAuthToken();
  if (token) {
    mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
      { urls: [`${APP_URL}/*`] },
      (details, callback) => {
        details.requestHeaders['X-App-Token'] = token;
        callback({ requestHeaders: details.requestHeaders });
      }
    );
  } else {
    console.warn('[gyraq] No auth token found yet at', TOKEN_FILE);
  }

  mainWindow.loadURL(APP_URL);
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);

  if (await checkHealth()) {
    createWindow();
    return;
  }

  const loading = new BrowserWindow({
    width: 420,
    height: 200,
    resizable: false,
    title: 'Gyraq Lead Scraper',
    icon: ICON_PATH,
  });
  loading.loadURL(loadingHtml());

  await startBackend();
  const ok = await waitForHealth(120000);
  loading.close();

  if (ok) {
    createWindow();
  } else {
    const errWin = new BrowserWindow({ width: 520, height: 260, icon: ICON_PATH });
    errWin.loadURL(errorHtml());
  }
});

app.on('window-all-closed', () => {
  // The backend is an always-on service by design (Docker container or a
  // detached native process) - closing the window shouldn't stop it.
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
