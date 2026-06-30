#!/usr/bin/env python3
"""CN-Project control panel — stdlib only, no pip/venv required."""

import json
import os
import queue
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent
STATIC_DIR = UI_DIR / "static"
TEMPLATE = UI_DIR / "templates" / "index.html"
GRAPHS_DIR = PROJECT_ROOT / "results" / "graphs"
ALLOWED_TARGETS = frozenset({"setup", "test-all", "analyze", "down"})

GRAPH_LABELS = {
    "validacao_overhead": "Validação — Overhead",
    "validacao_tempo": "Validação — Tempo",
    "eficiencia_pacotes": "Eficiência de pacotes",
    "vazao_por_cenario": "Vazão por cenário",
    "tempo_transferencia_bar": "Tempo de transferência",
    "retransmissoes_comparativas": "Retransmissões comparativas",
    "linha_bytes_app_vs_tcpdump": "Bytes — App vs tcpdump",
    "linha_tempo_app_vs_tcpdump": "Tempo — App vs tcpdump",
    "retransmissoes_rudp": "Retransmissões R-UDP",
    "tempo_transferencia_linha": "Tempo de transferência (linha)",
}


def _list_graphs() -> list[dict]:
    items = []
    if not GRAPHS_DIR.is_dir():
        return items
    for path in sorted(GRAPHS_DIR.glob("*.png")):
        stem = path.stem
        items.append(
            {
                "id": stem,
                "label": GRAPH_LABELS.get(stem, stem.replace("_", " ").title()),
                "url": f"/graphs/{path.name}",
            }
        )
    return items

_run_lock = threading.Lock()
_active_job: dict | None = None


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _run_make(target: str, log_queue: queue.Queue) -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        ["make", target],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log_queue.put({"type": "log", "line": _strip_ansi(line.rstrip("\n"))})
    proc.wait()
    return proc.returncode


def _json_response(handler: BaseHTTPRequestHandler, code: int, data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class ControlPanelHandler(BaseHTTPRequestHandler):
    server_version = "CN-Project-UI/1.0"

    def log_message(self, fmt, *args):
        pass

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _serve_bytes(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        suffix = path.suffix.lower()
        types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }
        self._serve_bytes(path.read_bytes(), types.get(suffix, "application/octet-stream"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/":
            return self._serve_file(TEMPLATE)
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            safe = Path(rel)
            if ".." in safe.parts:
                self.send_error(403)
                return
            return self._serve_file(STATIC_DIR / safe)

        if path == "/api/status":
            with _run_lock:
                if _active_job is None:
                    return _json_response(self, 200, {"running": False})
                return _json_response(
                    self,
                    200,
                    {
                        "running": True,
                        "target": _active_job["target"],
                        "started_at": _active_job["started_at"],
                    },
                )

        if path == "/api/stream":
            return self._handle_stream()

        if path == "/api/graphs":
            return _json_response(self, 200, {"graphs": _list_graphs()})

        if path.startswith("/graphs/"):
            name = path[len("/graphs/") :]
            if ".." in name or "/" in name or not name.endswith(".png"):
                self.send_error(403)
                return
            return self._serve_file(GRAPHS_DIR / name)

        self.send_error(404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            self.send_error(404)
            return
        self._handle_run()

    def _handle_run(self) -> None:
        global _active_job
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            return _json_response(self, 400, {"error": "JSON inválido"})

        target = data.get("target", "").replace("_", "-")
        if target not in ALLOWED_TARGETS:
            return _json_response(self, 400, {"error": f"Alvo inválido: {target}"})

        with _run_lock:
            if _active_job is not None:
                return _json_response(self, 409, {"error": "Já existe uma tarefa em execução."})

            log_queue: queue.Queue = queue.Queue()
            _active_job = {
                "target": target,
                "queue": log_queue,
                "started_at": time.time(),
            }

        def worker():
            global _active_job
            code = _run_make(target, log_queue)
            log_queue.put({"type": "done", "code": code, "success": code == 0})
            with _run_lock:
                _active_job = None

        threading.Thread(target=worker, daemon=True).start()
        _json_response(self, 200, {"ok": True, "target": target})

    def _handle_stream(self) -> None:
        with _run_lock:
            job = _active_job

        if job is None:
            return _json_response(self, 404, {"error": "Nenhuma tarefa ativa."})

        log_queue: queue.Queue = job["queue"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def send_event(payload: dict) -> None:
            line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        send_event({"type": "start", "target": job["target"]})
        while True:
            try:
                msg = log_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            send_event(msg)
            if msg.get("type") == "done":
                break


def main() -> None:
    port = int(os.environ.get("CN_UI_PORT", "5050"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ControlPanelHandler)
    print(f"CN-Project UI → http://127.0.0.1:{port}")
    print(f"Projeto: {PROJECT_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
