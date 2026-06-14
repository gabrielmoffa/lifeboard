"""Local browser UI for manually arranging Lifeboard widgets."""

import asyncio
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from lifeboard.board_engine import (
    apply_layout_edits,
    auto_layout,
    checkpoint_for_undo,
    load_board,
    remove_widget,
)
from lifeboard.phone_board import (
    add_widget_to_phone,
    apply_phone_layout_edits,
    auto_layout_phone,
    list_available_mac_widgets,
    remove_widget_from_phone,
    resolve_phone_board,
)
from lifeboard.renderer import render_and_set_wallpaper


class LayoutEditor:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(18)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if not self._server:
            raise RuntimeError("Layout editor is not running")
        host, port = self._server.server_address
        return f"http://{host}:{port}/?token={self.token}"

    def start(self) -> str:
        if self._server:
            return self.url

        editor = self

        class Handler(LayoutEditorHandler):
            layout_editor = editor

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="lifeboard-layout-editor",
            daemon=True,
        )
        self._thread.start()
        return self.url

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None


class LayoutEditorHandler(BaseHTTPRequestHandler):
    layout_editor: LayoutEditor

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(_EDITOR_HTML)
            return
        if path == "/api/board":
            if not self._authorized():
                self._send_json({"error": "Unauthorized"}, status=403)
                return
            self._send_json(self._board_for_mode(self._mode()))
            return
        self.send_error(404)

    def do_POST(self):
        if not self._authorized():
            self._send_json({"error": "Unauthorized"}, status=403)
            return

        path = urlparse(self.path).path
        mode = self._mode()
        payload = self._read_json()
        mac_board = load_board()

        if path == "/api/layout":
            checkpoint_for_undo()
            if mode == "phone":
                apply_phone_layout_edits(payload.get("widgets", []))
            else:
                apply_layout_edits(mac_board, payload.get("widgets", []))
            self._render_wallpaper(mac_board)
            self._send_json({"ok": True, "board": self._board_for_mode(mode)})
            return

        if path == "/api/auto-layout":
            checkpoint_for_undo()
            if mode == "phone":
                auto_layout_phone()
            else:
                auto_layout(mac_board)
            self._render_wallpaper(mac_board)
            self._send_json({"ok": True, "board": self._board_for_mode(mode)})
            return

        if path == "/api/widget/delete":
            widget_id = payload.get("id", "")
            checkpoint_for_undo()
            if mode == "phone":
                if not remove_widget_from_phone(widget_id):
                    self._send_json({"error": "Widget not on phone"}, status=404)
                    return
            else:
                if not remove_widget(mac_board, widget_id):
                    self._send_json({"error": "Widget not found"}, status=404)
                    return
            self._render_wallpaper(mac_board)
            self._send_json({"ok": True, "board": self._board_for_mode(mode)})
            return

        if path == "/api/widget/add-to-phone":
            widget_id = payload.get("id", "")
            if not any(w["id"] == widget_id for w in mac_board.get("widgets", [])):
                self._send_json({"error": "Widget not found on Mac board"}, status=404)
                return
            add_widget_to_phone(widget_id)
            self._render_wallpaper(mac_board)
            self._send_json({"ok": True, "board": self._board_for_mode("phone")})
            return

        self.send_error(404)

    def _mode(self) -> str:
        params = parse_qs(urlparse(self.path).query)
        mode = (params.get("mode") or ["mac"])[0]
        return "phone" if mode == "phone" else "mac"

    def _board_for_mode(self, mode: str) -> dict:
        mac_board = load_board()
        if mode == "phone":
            phone = resolve_phone_board(mac_board)
            payload = _public_board(phone)
            payload["mode"] = "phone"
            payload["available_mac_widgets"] = list_available_mac_widgets(mac_board)
            return payload
        payload = _public_board(mac_board)
        payload["mode"] = "mac"
        return payload

    def log_message(self, _format, *_args):
        return

    def _authorized(self) -> bool:
        params = parse_qs(urlparse(self.path).query)
        return params.get("token") == [self.layout_editor.token]

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _render_wallpaper(self, board: dict):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(render_and_set_wallpaper(board))
        finally:
            loop.close()

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _public_board(board: dict) -> dict:
    return {
        "theme": board.get("theme", ""),
        "resolution": board.get("resolution", [2560, 1600]),
        "widgets": [
            {
                "id": w.get("id"),
                "description": w.get("description", ""),
                "position": w.get("position", [0, 0]),
                "size": w.get("size", [10, 10]),
                "z_index": w.get("z_index", 0),
                "data_provider": w.get("data_provider", ""),
            }
            for w in board.get("widgets", [])
        ],
    }


_EDITOR_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lifeboard Layout Editor</title>
<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #172026;
  background: #eef2f5;
}
button, input { font: inherit; }
.shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 16px;
  min-height: 100vh;
  padding: 16px;
}
.mode-toggle {
  display: flex;
  gap: 0;
  margin-bottom: 4px;
}
.mode-toggle button {
  flex: 1;
  border-radius: 0;
  border: 1px solid #9aa6b2;
  background: #f8fafc;
}
.mode-toggle button.active {
  background: #0f766e;
  color: white;
  border-color: #0f766e;
}
.available-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
  padding: 6px;
  border: 1px solid #cbd5df;
  background: #f8fafc;
}
.available-list h2 {
  margin: 0 0 4px;
  font-size: 13px;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: .04em;
}
.available-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: white;
  border: 1px solid #cbd5df;
  font-size: 12px;
}
.available-item button {
  min-height: 26px;
  padding: 0 10px;
  border: 1px solid #0f766e;
  background: #0f766e;
  color: white;
  font-size: 12px;
}
.available-item .name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.available-empty {
  color: #94a3b8;
  font-size: 12px;
  padding: 6px 4px;
}
.stage-wrap {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.stage {
  position: relative;
  width: min(100%, calc((100vh - 32px) * var(--aspect)));
  aspect-ratio: var(--aspect);
  overflow: hidden;
  background: #0e1116;
  border: 1px solid #96a1ad;
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.22);
}
.grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.08) 1px, transparent 1px);
  background-size: 5% 5%;
}
.widget {
  position: absolute;
  min-width: 24px;
  min-height: 18px;
  border: 1px solid rgba(255,255,255,.82);
  background: rgba(24, 33, 43, .84);
  color: #f8fafc;
  cursor: move;
  overflow: hidden;
  user-select: none;
}
.widget.selected {
  outline: 3px solid #36c5f0;
  outline-offset: 0;
}
.delete-widget {
  position: absolute;
  top: 5px;
  right: 5px;
  z-index: 2;
  width: 24px;
  height: 24px;
  min-height: 0;
  padding: 0;
  border: 1px solid rgba(255,255,255,.72);
  border-radius: 999px;
  background: rgba(15, 23, 42, .86);
  color: #fff;
  line-height: 20px;
  cursor: pointer;
}
.delete-widget:hover {
  background: #be123c;
  border-color: #fecdd3;
}
.label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 34px 8px 8px;
  height: 100%;
  min-width: 0;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
  font-size: 13px;
}
.meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #b9c3cf;
  font-size: 11px;
}
.resize {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 18px;
  height: 18px;
  cursor: nwse-resize;
}
.resize:after {
  content: "";
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 8px;
  height: 8px;
  border-right: 2px solid #fff;
  border-bottom: 2px solid #fff;
}
.panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  padding: 14px;
  background: #ffffff;
  border: 1px solid #cbd5df;
}
.panel h1 {
  margin: 0;
  font-size: 17px;
  line-height: 1.2;
}
.selected-name {
  min-height: 34px;
  color: #475569;
  font-size: 13px;
}
.controls {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #475569;
  font-size: 12px;
}
input {
  width: 100%;
  padding: 7px 8px;
  border: 1px solid #b8c2cc;
  color: #172026;
}
.actions {
  display: grid;
  gap: 8px;
}
button {
  min-height: 34px;
  border: 1px solid #9aa6b2;
  background: #f8fafc;
  color: #172026;
  cursor: pointer;
}
button.primary {
  border-color: #0f766e;
  background: #0f766e;
  color: white;
}
button:disabled {
  opacity: .55;
  cursor: default;
}
.status {
  min-height: 18px;
  color: #475569;
  font-size: 12px;
}
@media (max-width: 860px) {
  .shell { grid-template-columns: 1fr; }
  .panel { order: -1; }
}
</style>
</head>
<body>
<main class="shell">
  <section class="stage-wrap">
    <div class="stage" id="stage"><div class="grid"></div></div>
  </section>
  <aside class="panel">
    <h1>Layout Editor</h1>
    <div class="mode-toggle">
      <button id="modeMacBtn" class="active" type="button">Mac</button>
      <button id="modePhoneBtn" type="button">Phone</button>
    </div>
    <div class="selected-name" id="selectedName">Select a widget.</div>
    <div class="controls">
      <label>X %<input id="xInput" type="number" min="0" max="100" step="0.1"></label>
      <label>Y %<input id="yInput" type="number" min="0" max="100" step="0.1"></label>
      <label>W %<input id="wInput" type="number" min="3" max="100" step="0.1"></label>
      <label>H %<input id="hInput" type="number" min="3" max="100" step="0.1"></label>
    </div>
    <div class="actions">
      <button class="primary" id="saveBtn">Save and Render</button>
      <button id="autoBtn">Reset Layout</button>
      <button id="reloadBtn">Reload</button>
    </div>
    <div class="available-list" id="availableList" style="display:none">
      <h2>Add Mac widget to Phone</h2>
      <div id="availableItems"></div>
    </div>
    <div class="status" id="status"></div>
  </aside>
</main>
<script>
const token = new URLSearchParams(location.search).get("token") || "";
const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");
const selectedName = document.getElementById("selectedName");
const inputs = {
  x: document.getElementById("xInput"),
  y: document.getElementById("yInput"),
  w: document.getElementById("wInput"),
  h: document.getElementById("hInput")
};
const modeMacBtn = document.getElementById("modeMacBtn");
const modePhoneBtn = document.getElementById("modePhoneBtn");
const availableList = document.getElementById("availableList");
const availableItems = document.getElementById("availableItems");
let board = null;
let selectedId = null;
let drag = null;
let mode = "mac";

function apiUrl(path, extra = "") {
  const params = new URLSearchParams({ token, mode });
  if (extra) {
    for (const [k, v] of new URLSearchParams(extra)) params.set(k, v);
  }
  return `${path}?${params.toString()}`;
}

function setStatus(text) {
  statusEl.textContent = text;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function widgetName(widget) {
  return widget.description || widget.id;
}

function selectedWidget() {
  return board.widgets.find(w => w.id === selectedId);
}

function render() {
  stage.style.setProperty("--aspect", `${board.resolution[0]} / ${board.resolution[1]}`);
  stage.querySelectorAll(".widget").forEach(el => el.remove());
  for (const widget of board.widgets) {
    const el = document.createElement("div");
    el.className = "widget" + (widget.id === selectedId ? " selected" : "");
    el.dataset.id = widget.id;
    el.style.left = widget.position[0] + "%";
    el.style.top = widget.position[1] + "%";
    el.style.width = widget.size[0] + "%";
    el.style.height = widget.size[1] + "%";
    el.style.zIndex = widget.z_index;
    el.innerHTML = `<button class="delete-widget" type="button" aria-label="Delete widget" title="Delete widget">×</button><div class="label"><div class="name"></div><div class="meta"></div></div><div class="resize"></div>`;
    el.querySelector(".name").textContent = widgetName(widget);
    el.querySelector(".meta").textContent = `${widget.id} ${widget.data_provider || ""}`.trim();
    el.querySelector(".delete-widget").addEventListener("click", deleteWidget);
    el.addEventListener("pointerdown", startDrag);
    stage.appendChild(el);
  }
  syncPanel();
}

function syncPanel() {
  const widget = selectedWidget();
  const disabled = !widget;
  Object.values(inputs).forEach(input => input.disabled = disabled);
  if (!widget) {
    selectedName.textContent = "Select a widget.";
    for (const input of Object.values(inputs)) input.value = "";
    return;
  }
  selectedName.textContent = widgetName(widget);
  inputs.x.value = widget.position[0];
  inputs.y.value = widget.position[1];
  inputs.w.value = widget.size[0];
  inputs.h.value = widget.size[1];
}

function startDrag(event) {
  if (event.target.closest(".delete-widget")) return;
  const el = event.currentTarget;
  const widget = board.widgets.find(w => w.id === el.dataset.id);
  selectedId = widget.id;
  document.querySelectorAll(".widget.selected").forEach(node => node.classList.remove("selected"));
  el.classList.add("selected");
  const rect = stage.getBoundingClientRect();
  const resizing = event.target.classList.contains("resize");
  drag = {
    id: widget.id,
    resizing,
    startX: event.clientX,
    startY: event.clientY,
    rectW: rect.width,
    rectH: rect.height,
    position: [...widget.position],
    size: [...widget.size]
  };
  el.setPointerCapture(event.pointerId);
  window.addEventListener("pointermove", moveDrag);
  window.addEventListener("pointerup", endDrag, { once: true });
  syncPanel();
  event.preventDefault();
}

function moveDrag(event) {
  if (!drag) return;
  const widget = board.widgets.find(w => w.id === drag.id);
  const dx = (event.clientX - drag.startX) / drag.rectW * 100;
  const dy = (event.clientY - drag.startY) / drag.rectH * 100;
  if (drag.resizing) {
    widget.size[0] = round(clamp(drag.size[0] + dx, 3, 100 - widget.position[0]));
    widget.size[1] = round(clamp(drag.size[1] + dy, 3, 100 - widget.position[1]));
  } else {
    widget.position[0] = round(clamp(drag.position[0] + dx, 0, 100 - widget.size[0]));
    widget.position[1] = round(clamp(drag.position[1] + dy, 0, 100 - widget.size[1]));
  }
  render();
}

function endDrag() {
  window.removeEventListener("pointermove", moveDrag);
  drag = null;
}

function round(value) {
  return Math.round(value * 10) / 10;
}

function updateFromInputs() {
  const widget = selectedWidget();
  if (!widget) return;
  const width = clamp(Number(inputs.w.value), 3, 100);
  const height = clamp(Number(inputs.h.value), 3, 100);
  widget.size = [round(width), round(height)];
  widget.position = [
    round(clamp(Number(inputs.x.value), 0, 100 - width)),
    round(clamp(Number(inputs.y.value), 0, 100 - height))
  ];
  render();
}

for (const input of Object.values(inputs)) {
  input.addEventListener("change", updateFromInputs);
}

function renderAvailable() {
  if (mode !== "phone") {
    availableList.style.display = "none";
    return;
  }
  availableList.style.display = "flex";
  availableItems.innerHTML = "";
  const items = board.available_mac_widgets || [];
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "available-empty";
    empty.textContent = "All Mac widgets are already on the phone.";
    availableItems.appendChild(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "available-item";
    const label = document.createElement("div");
    label.className = "name";
    label.textContent = item.description || item.id;
    label.title = `${item.id} ${item.data_provider || ""}`.trim();
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "+";
    btn.addEventListener("click", () => addToPhone(item.id));
    row.appendChild(label);
    row.appendChild(btn);
    availableItems.appendChild(row);
  }
}

async function loadBoard() {
  setStatus("Loading...");
  const res = await fetch(apiUrl("/api/board"));
  board = await res.json();
  selectedId = board.widgets[0]?.id || null;
  render();
  renderAvailable();
  setStatus("");
}

async function saveLayout() {
  setStatus("Saving and rendering...");
  const widgets = board.widgets.map(w => ({ id: w.id, position: w.position, size: w.size }));
  const res = await fetch(apiUrl("/api/layout"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ widgets })
  });
  const payload = await res.json();
  board = payload.board;
  render();
  renderAvailable();
  setStatus("Saved.");
}

async function autoOrganize() {
  setStatus("Resetting and rendering...");
  const res = await fetch(apiUrl("/api/auto-layout"), { method: "POST" });
  const payload = await res.json();
  board = payload.board;
  selectedId = board.widgets[0]?.id || null;
  render();
  renderAvailable();
  setStatus("Reset.");
}

async function deleteWidget(event) {
  event.stopPropagation();
  const widget = board.widgets.find(w => w.id === event.currentTarget.closest(".widget").dataset.id);
  if (!widget) return;
  const verb = mode === "phone" ? "Remove from phone" : "Delete";
  if (!confirm(`${verb}: ${widgetName(widget)}?`)) return;
  setStatus("Saving and rendering...");
  const res = await fetch(apiUrl("/api/widget/delete"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: widget.id })
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || "Delete failed");
  board = payload.board;
  selectedId = board.widgets[0]?.id || null;
  render();
  renderAvailable();
  setStatus("Done.");
}

async function addToPhone(widgetId) {
  setStatus("Adding to phone...");
  const res = await fetch(apiUrl("/api/widget/add-to-phone"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: widgetId })
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || "Add failed");
  board = payload.board;
  selectedId = widgetId;
  render();
  renderAvailable();
  setStatus("Added.");
}

function setMode(next) {
  if (mode === next) return;
  mode = next;
  modeMacBtn.classList.toggle("active", mode === "mac");
  modePhoneBtn.classList.toggle("active", mode === "phone");
  loadBoard().catch(err => setStatus(err.message));
}

modeMacBtn.addEventListener("click", () => setMode("mac"));
modePhoneBtn.addEventListener("click", () => setMode("phone"));
document.getElementById("saveBtn").addEventListener("click", saveLayout);
document.getElementById("autoBtn").addEventListener("click", autoOrganize);
document.getElementById("reloadBtn").addEventListener("click", loadBoard);
loadBoard().catch(err => setStatus(err.message));
</script>
</body>
</html>
"""
