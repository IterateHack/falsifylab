"""FastAPI backend: serves recorded runs for replay, and streams live ones.

Replay is the default for the demo (plan section 5.6): the events of a finished
run are served as plain JSON and paced by the frontend's animation queue, which
cannot fail on stage. Live mode starts a real run in a worker thread and pushes
events over SSE as they are appended to the log.
"""
from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.events import EventLog, read_jsonl
from engine.runner import run_curriculum
from engine.specs import load_curriculum

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(__import__("os").environ.get("FL_RUNS_DIR", ROOT / "runs"))
REPLAYS_DIR = ROOT / "replays"
CURRICULUM = ROOT / "curricula" / "glp1r"
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="FalsifyLab", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# live runs, keyed by run_id
_LIVE: dict[str, dict[str, Any]] = {}
_LIVE_LOCK = threading.Lock()


def _run_dirs() -> list[Path]:
    out = []
    for base in (RUNS_DIR, REPLAYS_DIR):
        if base.exists():
            out.extend(p for p in sorted(base.iterdir())
                       if p.is_dir() and (p / "events.jsonl").exists())
    return out


def _find_run(run_id: str) -> Path:
    for p in _run_dirs():
        if p.name == run_id:
            return p
    raise HTTPException(404, f"no run {run_id!r}")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "runs": [p.name for p in _run_dirs()]}


@app.get("/api/curriculum")
def curriculum() -> dict[str, Any]:
    c = load_curriculum(CURRICULUM)
    return {
        "id": c.id, "title": c.title, "hypothesis": c.hypothesis,
        "experiments": [
            {"id": e.id, "order": e.order, "title": e.title, "type": e.type,
             "requires_lessons": e.requires_lessons,
             "papers": e.teaching.papers,
             "max_tool_calls": e.limits.max_tool_calls}
            for e in c.experiments
        ],
    }


@app.get("/api/runs")
def list_runs() -> dict[str, Any]:
    out = []
    for p in _run_dirs():
        nb = p / "notebook.json"
        meta: dict[str, Any] = {"run_id": p.name, "kind": p.parent.name}
        if nb.exists():
            try:
                data = json.loads(nb.read_text())
                cal = data.get("calibration", {})
                meta.update({
                    "n_entries": len(data.get("entries", [])),
                    "mean_score": cal.get("mean_score"),
                    "mean_confidence": cal.get("mean_confidence"),
                    "mean_gap": cal.get("mean_gap"),
                })
            except json.JSONDecodeError:
                pass
        with _LIVE_LOCK:
            meta["live"] = p.name in _LIVE and _LIVE[p.name]["status"] == "running"
        out.append(meta)
    return {"runs": out}


@app.get("/api/run/{run_id}/notebook")
def notebook(run_id: str) -> dict[str, Any]:
    p = _find_run(run_id) / "notebook.json"
    if not p.exists():
        raise HTTPException(404, "no notebook for this run yet")
    return json.loads(p.read_text())


@app.get("/api/run/{run_id}/events")
def events(run_id: str, since: int = 0,
           experiment: str | None = Query(default=None)) -> dict[str, Any]:
    evs = read_jsonl(_find_run(run_id) / "events.jsonl")
    out = []
    for e in evs:
        if e.seq <= since:
            continue
        if experiment and e.experiment_id != experiment:
            continue
        out.append({"seq": e.seq, "ts": e.ts, "run_id": e.run_id,
                    "experiment_id": e.experiment_id, "type": e.type,
                    "payload": e.payload})
    with _LIVE_LOCK:
        live = run_id in _LIVE and _LIVE[run_id]["status"] == "running"
    return {"run_id": run_id, "events": out, "count": len(out), "live": live}


@app.get("/api/run/{run_id}/stream")
def stream(run_id: str, since: int = 0) -> StreamingResponse:
    """SSE for a live run. Replays what already happened, then follows."""
    with _LIVE_LOCK:
        entry = _LIVE.get(run_id)
    if entry is None:
        raise HTTPException(404, f"{run_id} is not a live run; use /events for replay")

    q: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
    log: EventLog = entry["log"]

    def on_event(ev: Any) -> None:
        q.put({"seq": ev.seq, "ts": ev.ts, "run_id": ev.run_id,
               "experiment_id": ev.experiment_id, "type": ev.type,
               "payload": ev.payload})

    unsubscribe = log.subscribe(on_event)

    def gen() -> Iterator[str]:
        try:
            for ev in log.all(since_seq=since):
                yield _sse({"seq": ev.seq, "ts": ev.ts, "run_id": ev.run_id,
                            "experiment_id": ev.experiment_id, "type": ev.type,
                            "payload": ev.payload})
            while True:
                try:
                    item = q.get(timeout=15.0)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    with _LIVE_LOCK:
                        st = _LIVE.get(run_id, {}).get("status")
                    if st != "running":
                        break
                    continue
                if item is None:
                    break
                yield _sse(item)
                if item["type"] == "run_finished":
                    break
        finally:
            unsubscribe()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(payload: dict[str, Any]) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload, default=str)}\n\n"


class StartRun(BaseModel):
    run_id: str | None = None
    backend: str = "local"
    use_lessons: bool = True
    only: list[str] | None = None


@app.post("/api/run")
def start_run(body: StartRun) -> dict[str, Any]:
    run_id = body.run_id or f"live_{uuid.uuid4().hex[:8]}"
    with _LIVE_LOCK:
        if run_id in _LIVE and _LIVE[run_id]["status"] == "running":
            raise HTTPException(409, f"{run_id} is already running")

    # The log is created here rather than inside the thread so the SSE endpoint
    # can subscribe before the first event lands.
    log = EventLog(RUNS_DIR / run_id, run_id)
    with _LIVE_LOCK:
        _LIVE[run_id] = {"status": "running", "log": log, "error": None}

    def work() -> None:
        try:
            run_curriculum(
                curriculum_root=CURRICULUM, run_id=run_id, runs_dir=RUNS_DIR,
                backend=body.backend, use_lessons=body.use_lessons, only=body.only,
                existing_log=log,
            )
            status, err = "finished", None
        except Exception as exc:
            status, err = "failed", f"{type(exc).__name__}: {exc}"
            try:
                log.append("error", {"fatal": True, "error": err})
            except Exception:
                pass
        with _LIVE_LOCK:
            _LIVE[run_id].update({"status": status, "error": err})

    threading.Thread(target=work, name=f"run-{run_id}", daemon=True).start()
    return {"run_id": run_id, "status": "running",
            "stream": f"/api/run/{run_id}/stream"}


@app.get("/api/run/{run_id}/status")
def run_status(run_id: str) -> dict[str, Any]:
    with _LIVE_LOCK:
        entry = _LIVE.get(run_id)
        if entry:
            return {"run_id": run_id, "status": entry["status"],
                    "error": entry["error"]}
    _find_run(run_id)
    return {"run_id": run_id, "status": "recorded", "error": None}


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
