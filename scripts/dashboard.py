#!/usr/bin/env python3
"""Serve the local job dashboard and recent live SDK events."""

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trace_data import scheduler_event
from live_data import LiveCache
from export_perfetto import export_trace


ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / 'traces'
UI = ROOT / 'ui'
LIVE = LiveCache()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI), **kwargs)

    def log_message(self, _format, *_args):
        # The browser polls both live endpoints; avoid flooding the terminal.
        pass

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        request = urlparse(self.path)
        query = parse_qs(request.query)
        if request.path == '/api/traces':
            files = sorted(TRACES.glob('*.jobs.json'),
                           key=lambda item: item.stat().st_mtime, reverse=True)
            self.send_json([{'name': item.name, 'modified': item.stat().st_mtime}
                            for item in files])
            return
        if request.path in ('/api/data', '/api/export'):
            name = query.get('name', [''])[0]
            if Path(name).name != name or not name.endswith('.jobs.json'):
                self.send_json({'error': 'invalid trace name'}, 400)
                return
            path = TRACES / name
            if not path.is_file():
                self.send_json({'error': 'trace not found'}, 404)
                return
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if request.path == '/api/export':
                    payload = json.dumps(export_trace(data), ensure_ascii=False).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    # ASCII filename avoids header encoding errors for Unicode trace names.
                    self.send_header('Content-Disposition', 'attachment; filename=watcher.perfetto.json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_json(data)
            except (OSError, json.JSONDecodeError):
                self.send_json({'error': 'trace data is incomplete'}, 503)
            return
        if request.path == '/api/live':
            name = query.get('name', [''])[0]
            if name:
                if Path(name).name != name or not name.endswith('.events.log'):
                    self.send_json({'error': 'invalid event name'}, 400)
                    return
                path = TRACES / name
            else:
                files = sorted(TRACES.glob('live-*.events.log'),
                               key=lambda item: item.stat().st_mtime, reverse=True)
                path = files[0] if files else None
            if path is None or not path.is_file():
                self.send_json({'name': None, 'events': [], 'scheduler': [], 'active': False})
                return
            try:
                self.send_json(LIVE.get(path))
            except OSError as exc:
                self.send_json({'error': str(exc), 'events': [], 'scheduler': []}, 503)
            return
        super().do_GET()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Open http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
