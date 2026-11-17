"""Incremental app-first live history; unrelated kernel events never evict it."""
import json
import re
import threading
import time
from collections import deque
from pathlib import Path

from trace_data import application_event, scheduler_event


class LiveFeed:
    def __init__(self, path, max_events=10000, max_scheduler=20000):
        self.path = Path(path)
        self.report = self.path.with_name(self.path.name.replace('.events.log', '.txt'))
        self.session = self.path.with_name(self.path.name.replace('.events.log', '.session.json'))
        self.events = deque(maxlen=max_events)
        self.scheduler = deque(maxlen=max_scheduler)
        self.tids, self.cpus, self.keys = set(), set(), set()
        self.positions = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.worker = None
        self.error = None
        self.history_limited = False
        self.matcher = None

    def _lines(self, path, limit):
        """Read only new complete lines, including growth after an earlier poll."""
        if not path.is_file():
            return []
        info = path.stat()
        identity = (info.st_dev, info.st_ino)
        saved_identity, offset = self.positions.get(path, (identity, 0))
        if identity != saved_identity or info.st_size < offset:
            offset = 0
        with path.open('rb') as source:
            source.seek(offset)
            block = source.read(min(limit, max(0, info.st_size - offset)))
        complete = block.rfind(b'\n') + 1
        self.positions[path] = (identity, offset + complete)
        return block[:complete].splitlines()

    def update(self):
        """Process one bounded batch; exposed for deterministic regression tests."""
        with self.lock:
            old_tids = self.tids.copy()
            for line in self._lines(self.path, 2 * 1024 * 1024):
                event = application_event(line.decode('utf-8', errors='replace'))
                if event:
                    self.tids.add(event['tid'])
                    self.history_limited |= len(self.events) == self.events.maxlen
                    self.events.append(event)
            if self.tids != old_tids:
                ids = b'|'.join(str(tid).encode() for tid in sorted(self.tids))
                # Both trace_pipe key/value and trace-cmd report task formats.
                self.matcher = re.compile(rb'\b(?:prev_pid|next_pid|pid)=(?:' + ids +
                                          rb')(?!\d)|:(?:' + ids + rb')\s+\[')
                # SDK markers can reach disk just after a thread's first switch.
                # Revisit a bounded overlap; event keys prevent double insertion.
                if self.report in self.positions:
                    identity, offset = self.positions[self.report]
                    self.positions[self.report] = (identity, max(0, offset - 4 * 1024 * 1024))
            for raw in self._lines(self.report, 4 * 1024 * 1024):
                if not self.matcher or not self.matcher.search(raw):
                    continue
                event = scheduler_event(raw.decode('utf-8', errors='replace'))
                if not event or not (event.get('prev_tid') in self.tids or
                                     event.get('next_tid') in self.tids or
                                     event.get('tid') in self.tids):
                    continue
                key = (event['time_s'], event['cpu'], event['kind'],
                       event.get('prev_tid'), event.get('next_tid'), event.get('tid'))
                if key in self.keys:
                    continue
                if len(self.scheduler) == self.scheduler.maxlen:
                    self.history_limited = True
                    discarded = self.scheduler[0]
                    self.keys.discard((discarded['time_s'], discarded['cpu'], discarded['kind'],
                                       discarded.get('prev_tid'), discarded.get('next_tid'), discarded.get('tid')))
                self.keys.add(key)
                self.scheduler.append(event)
                if event['kind'] == 'sched_switch':
                    self.cpus.add(event['cpu'])
            self.error = None

    def _run(self):
        while not self.stopped.is_set():
            try:
                self.update()
            except (OSError, ValueError) as exc:
                with self.lock:
                    self.error = str(exc)
            # Yield between bounded batches; scan historical files in background.
            self.stopped.wait(0.02 if self.loading() else 0.1)

    def loading(self):
        try:
            with self.lock:
                offset = self.positions.get(self.report, (None, 0))[1]
            return self.report.is_file() and self.report.stat().st_size - offset > 1
        except OSError:
            return False

    def start(self):
        if self.worker is None:
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()

    def close(self):
        self.stopped.set()

    def snapshot(self):
        try:
            session = json.loads(self.session.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            session = {}
        with self.lock:
            events = list(self.events)
            scheduler = sorted(self.scheduler, key=lambda e: (float(e['time_s']), e['cpu']))
            tids, cpus = sorted(self.tids), sorted(self.cpus)
            offset = self.positions.get(self.report, (None, 0))[1]
            error, limited = self.error, self.history_limited
        size = self.report.stat().st_size if self.report.is_file() else 0
        mtime = max(self.path.stat().st_mtime,
                    self.report.stat().st_mtime if self.report.is_file() else 0)
        phase = session.get('phase')
        active = phase in ('starting', 'recording') if phase else time.time() - mtime < 2
        return {'name': self.path.name, 'events': events, 'scheduler': scheduler,
                'thread_ids': tids, 'cpus': cpus, 'active': active, 'phase': phase,
                'app_end_s': session.get('app_end_s'),
                'now_s': str(time.monotonic()), 'history_limited': limited,
                'loading': size - offset > 4 * 1024 * 1024 or (not scheduler and size > offset),
                'bytes_read': offset, 'bytes_total': size,
                'scheduler_missing': not self.report.is_file(), 'error': error}


class LiveCache:
    def __init__(self):
        self.feeds = {}
        self.lock = threading.Lock()

    def get(self, path):
        path = Path(path)
        with self.lock:
            if path not in self.feeds:
                # Bound readers even if a client repeatedly selects old captures.
                if len(self.feeds) >= 3:
                    key = next(iter(self.feeds))
                    self.feeds.pop(key).close()
                self.feeds[path] = LiveFeed(path)
                self.feeds[path].start()
            feed = self.feeds[path]
        return feed.snapshot()
