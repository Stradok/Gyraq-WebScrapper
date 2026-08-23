#!/usr/bin/env bash
set -e

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "Installing Python dependencies..."
uv sync

echo "Installing Chromium for Playwright..."
uv run playwright install chromium
if command -v apt-get >/dev/null 2>&1; then
  uv run playwright install-deps chromium || echo "Could not auto-install system libraries (try 'sudo uv run playwright install-deps chromium')."
fi

echo
echo "Setup complete. Start it with:"
echo "  ./run.sh"
