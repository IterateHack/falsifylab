"""Modal deployment: the image, the sandbox-backed runs and the web endpoint.

NOTE ON STATUS: this module is written against Modal's documented API but has
not been executed - the development machine had no Modal credentials. Everything
it depends on (the Executor contract, the scorer isolation, the event log) is
exercised by the local backend, so switching backends should be a config change.
Treat the first `modal deploy` as the real test.

    modal setup
    modal run api/modal_app.py::build_datasets     # populate the volume
    modal deploy api/modal_app.py
"""
from __future__ import annotations

import modal

APP_NAME = "falsifylab"

# One image with the science stack, matching what the local sandbox provides.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "anthropic>=0.69.0", "fastapi>=0.115.0", "uvicorn[standard]>=0.32.0",
        "pyyaml>=6.0.2", "numpy>=2.0.0", "pandas>=2.2.0", "scipy>=1.14.0",
        "requests>=2.32.0", "pillow>=10.4.0",
    )
    .add_local_dir("engine", "/root/engine")
    .add_local_dir("sandbox", "/root/sandbox")
    .add_local_dir("api", "/root/api")
    .add_local_dir("curricula", "/root/curricula")
    .add_local_dir("web/dist", "/root/web/dist")
)

# The sandbox image is deliberately separate and smaller: it runs untrusted
# agent code and has no reason to carry the Anthropic SDK or the API layer.
sandbox_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("numpy>=2.0.0", "pandas>=2.2.0", "scipy>=1.14.0",
                 "matplotlib>=3.9.0", "biopython>=1.84")
)

app = modal.App(APP_NAME)
runs_volume = modal.Volume.from_name("falsifylab-runs", create_if_missing=True)
data_volume = modal.Volume.from_name("falsifylab-data", create_if_missing=True)
secrets = [modal.Secret.from_name("anthropic-api-key")]


@app.function(image=image, volumes={"/data": data_volume}, timeout=1800)
def build_datasets() -> None:
    """Fetch the curriculum datasets once, into the shared volume."""
    import shutil
    import sys
    sys.path.insert(0, "/root")
    from curricula.glp1r import fetch

    fetch.main()
    shutil.copytree("/root/curricula/glp1r/data", "/data/glp1r/data", dirs_exist_ok=True)
    shutil.copytree("/root/curricula/glp1r/private", "/data/glp1r/private",
                    dirs_exist_ok=True)
    data_volume.commit()
    print("datasets committed to the falsifylab-data volume")


@app.function(
    image=image, secrets=secrets,
    volumes={"/runs": runs_volume, "/data": data_volume},
    timeout=3600, max_containers=4,
)
def run_curriculum_remote(run_id: str, use_lessons: bool = True,
                          only: list[str] | None = None) -> dict:
    """Run the whole curriculum with agent code executing in Modal Sandboxes."""
    import sys
    sys.path.insert(0, "/root")
    from engine.runner import run_curriculum

    result = run_curriculum(
        curriculum_root="/root/curricula/glp1r", run_id=run_id, runs_dir="/runs",
        backend="modal", use_lessons=use_lessons, only=only,
    )
    runs_volume.commit()
    return result.summary()


@app.function(image=image, secrets=secrets,
              volumes={"/runs": runs_volume, "/data": data_volume}, timeout=3600)
def control_experiment(run_id_prefix: str = "control") -> dict:
    """The learning evidence: the same curriculum with and without lesson cards.

    Both arms run in parallel containers, so the comparison costs one run's
    wall-clock time rather than two (plan section 10.4).
    """
    arms = [(f"{run_id_prefix}_with_lessons", True),
            (f"{run_id_prefix}_no_lessons", False)]
    results = list(run_curriculum_remote.starmap(
        [(rid, lessons, None) for rid, lessons in arms]))
    summary = {rid: res for (rid, _), res in zip(arms, results)}
    with_mean = summary[arms[0][0]]["calibration"]["mean_score"]
    without_mean = summary[arms[1][0]]["calibration"]["mean_score"]
    summary["delta_mean_score"] = (
        None if with_mean is None or without_mean is None
        else round(with_mean - without_mean, 4))
    return summary


@app.function(image=image, secrets=secrets,
              volumes={"/runs": runs_volume, "/data": data_volume},
              min_containers=1)
@modal.asgi_app()
def web():
    import os
    import sys
    sys.path.insert(0, "/root")
    os.environ["FL_RUNS_DIR"] = "/runs"
    from api.main import app as fastapi_app
    return fastapi_app
