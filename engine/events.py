"""Append-only event log. The single source of truth for a run (plan section 5.6).

Everything the UI and the notebook render is a view over this log. JSONL is the
durable record; SQLite is an index for querying without replaying the file.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

EVENT_TYPES = (
    "run_started",
    "experiment_started",
    "prediction_written",
    "plan_written",
    "tool_call",
    "tool_result",
    "scored",
    "teaching_started",
    "lesson_learned",
    "notebook_entry_ready",
    "experiment_done",
    "run_finished",
    "error",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    seq: int
    ts: str
    run_id: str
    experiment_id: str | None
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Event":
        return Event(
            seq=d["seq"],
            ts=d["ts"],
            run_id=d["run_id"],
            experiment_id=d.get("experiment_id"),
            type=d["type"],
            payload=d.get("payload") or {},
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq           INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    experiment_id TEXT,
    type          TEXT NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_exp ON events(experiment_id, seq);
"""


class EventLog:
    """Append-only log with a JSONL file of record and a SQLite index.

    Thread-safe: the agent loop appends from a worker thread while the SSE
    endpoint reads. Subscribers are notified synchronously after the write
    lands on disk, so a subscriber never sees an event that is not durable.
    """

    def __init__(self, run_dir: str | Path, run_id: str):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.jsonl_path = self.run_dir / "events.jsonl"
        self.db_path = self.run_dir / "events.db"
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[Event], None]] = []
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self._seq = self._max_seq()

    def _max_seq(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
        return int(row[0])

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._subscribers:
                    self._subscribers.remove(fn)

        return unsubscribe

    def append(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        experiment_id: str | None = None,
    ) -> Event:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}; expected one of {EVENT_TYPES}")
        with self._lock:
            self._seq += 1
            ev = Event(
                seq=self._seq,
                ts=utc_now(),
                run_id=self.run_id,
                experiment_id=experiment_id,
                type=type,
                payload=payload or {},
            )
            with self.jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(ev.to_json() + "\n")
                fh.flush()
            self._db.execute(
                "INSERT INTO events (seq, ts, run_id, experiment_id, type, payload)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ev.seq, ev.ts, ev.run_id, ev.experiment_id, ev.type,
                 json.dumps(ev.payload, separators=(",", ":"))),
            )
            self._db.commit()
            subscribers = list(self._subscribers)
        for fn in subscribers:
            try:
                fn(ev)
            except Exception:  # a broken subscriber must never break the run
                pass
        return ev

    def all(self, since_seq: int = 0) -> list[Event]:
        rows = self._db.execute(
            "SELECT seq, ts, run_id, experiment_id, type, payload FROM events"
            " WHERE seq > ? ORDER BY seq",
            (since_seq,),
        ).fetchall()
        return [
            Event(seq=r[0], ts=r[1], run_id=r[2], experiment_id=r[3],
                  type=r[4], payload=json.loads(r[5]))
            for r in rows
        ]

    def for_experiment(self, experiment_id: str) -> list[Event]:
        return [e for e in self.all() if e.experiment_id == experiment_id]

    def close(self) -> None:
        self._db.close()


def read_jsonl(path: str | Path) -> list[Event]:
    """Load a recorded run from its JSONL file (replay mode)."""
    out: list[Event] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(Event.from_dict(json.loads(line)))
    return out


def replay(events: list[Event], speed: float = 1.0,
           min_gap_s: float = 0.0) -> Iterator[Event]:
    """Yield recorded events, re-creating the original pacing.

    `speed` > 1 plays faster. `min_gap_s` floors the gap so a run that was
    fast in wall-clock time still reads as deliberate in the demo.
    """
    prev: datetime | None = None
    for ev in events:
        ts = datetime.strptime(ev.ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if prev is not None:
            gap = max((ts - prev).total_seconds() / max(speed, 1e-6), min_gap_s)
            if gap > 0:
                time.sleep(min(gap, 10.0))
        prev = ts
        yield ev
