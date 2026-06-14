#!/bin/bash
set -e

echo "=== Lifeboard Setup ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Install Python 3.11+ first."
    exit 1
fi

# Create venv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

echo "Installing Playwright browsers..."
.venv/bin/playwright install chromium

echo "Compiling wallpaper helper..."
swiftc set_wallpaper.swift -o set_wallpaper

# Create config dir
mkdir -p ~/.lifeboard/output

# Prompt for API key if not set
if [ ! -f ~/.lifeboard/config.json ]; then
    echo ""
    echo "Lifeboard works with any OpenAI-compatible API (OpenRouter, OpenAI, Together, etc.) or Anthropic."
    echo "Default: OpenRouter (https://openrouter.ai/api/v1)"
    read -p "Enter your API key (or press Enter to skip): " api_key
    .venv/bin/python - <<'PY'
import json
from pathlib import Path

config_path = Path.home() / ".lifeboard" / "config.json"
config_path.write_text(json.dumps({"theme": "slate"}, indent=2) + "\n")
PY
    if [ -n "$api_key" ]; then
        LIFEBOARD_API_KEY="$api_key" .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

secrets_path = Path.home() / ".lifeboard" / "secrets.json"
secrets_path.write_text(
    json.dumps({"ai_api_key": os.environ["LIFEBOARD_API_KEY"]}, indent=2) + "\n"
)
PY
        chmod 600 ~/.lifeboard/secrets.json
        echo "API key saved to ~/.lifeboard/secrets.json"
    else
        echo "Config created. Set your API key later in ~/.lifeboard/secrets.json"
    fi
    echo ""
    echo "To change provider, edit ~/.lifeboard/config.json:"
    echo "  ai_base_url — API endpoint (default: OpenRouter)"
    echo "  ai_model    — model name (default: anthropic/claude-sonnet-4.6)"
fi

# Register MCP server with Claude Code if available
if command -v claude &> /dev/null; then
    echo "Registering Lifeboard MCP server with Claude Code..."
    claude mcp add -s user lifeboard -- "$(pwd)/.venv/bin/python" -m lifeboard.mcp_server 2>/dev/null && \
        echo "MCP server registered! Restart Claude Code to use lifeboard tools." || \
        echo "Warning: Could not register MCP server. You can do it manually with:"
        echo "  claude mcp add -s user lifeboard -- $(pwd)/.venv/bin/python -m lifeboard.mcp_server"
else
    echo "Claude Code not found. To add the MCP server later, run:"
    echo "  claude mcp add -s user lifeboard -- $(pwd)/.venv/bin/python -m lifeboard.mcp_server"
fi

# Install LaunchAgent so Lifeboard starts on login
PLIST_NAME="com.lifeboard.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/.venv/bin/python</string>
        <string>${PROJECT_DIR}/run.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${HOME}/.lifeboard/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/.lifeboard/stderr.log</string>
</dict>
</plist>
EOF

# Load it now (unload first in case of re-run)
launchctl bootout gui/$(id -u) "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PLIST_PATH"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Lifeboard is running and will auto-start on login."
echo "To stop:   launchctl bootout gui/\$(id -u) $PLIST_PATH"
echo "To restart: launchctl kickstart -k gui/\$(id -u)/${PLIST_NAME}"
echo ""
