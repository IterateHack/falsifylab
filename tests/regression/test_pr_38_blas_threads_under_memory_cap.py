"""PR #38: the local sandbox caps the child's address space (FL_MEM_BYTES,
RLIMIT_AS). OpenBLAS, bundled by the numpy wheel, starts one worker per
visible CPU when it loads and reserves per-thread buffers, so the import needs
more address space the more cores the host has. On a 32-CPU host under the
2 GiB cap `import numpy, scipy, pandas` died with "OpenBLAS error: Memory
allocation still failed", the snippet printed nothing, and the path audit
labelled an honest run REWARD_HACK (`answer_not_in_run_output`).

Direction: false positive (an honest run scored as a reward hack).

The failure needs (visible cores) x (per-thread allocation) to exceed the cap,
so instead of a many-core host this test lowers the cap. It calibrates on the
host it runs on: it finds the smallest cap the pinned import fits in, then
requires, just above that cap, that the same import with the thread limit
removed fails, and that it fits again once the cap allows for the extra
threads. If the unpinned import fits, the test fails rather than passing
without exercising the bug. Measured on an 8-CPU host (numpy 2.5.3 and
2.2.6): each visible CPU beyond the first adds roughly 32-40 MiB to the
unpinned import, about twice that with scipy's own OpenBLAS loaded too.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[2] / "lab"
if str(LAB) not in sys.path:
    sys.path.append(str(LAB))

from sandbox import local  # noqa: E402
from sandbox.local import LocalExecutor, child_env  # noqa: E402

MIB = 1024 ** 2
SNIPPET = "import numpy\nprint('imported', numpy.__version__)\n"


def _visible_cpus() -> int:
    # OpenBLAS sizes its pool from the affinity mask, not os.cpu_count().
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _numpy_in_isolated_child() -> bool:
    # The sandbox runs `python -I`, which ignores the user site.
    return subprocess.run([sys.executable, "-I", "-c", "import numpy"],
                          capture_output=True).returncode == 0


pytestmark = [
    pytest.mark.skipif(sys.platform == "win32",
                       reason="the address-space cap is POSIX-only (setrlimit)"),
    pytest.mark.skipif(not _numpy_in_isolated_child(),
                       reason="numpy is not importable under `python -I` here "
                              "(user-site install); the sandbox could not import it"),
]


def _imports(cap_mib: int, pinned: bool) -> bool:
    with pytest.MonkeyPatch.context() as mp:
        if not pinned:
            def unpinned_env(*args, **kwargs):
                env = child_env(*args, **kwargs)
                env.pop("OPENBLAS_NUM_THREADS", None)
                return env
            mp.setattr(local, "child_env", unpinned_env)
        with LocalExecutor(name="pr38", mem_bytes=cap_mib * MIB) as ex:
            res = ex.run_python(SNIPPET, timeout_s=60)
    return res.ok and "imported" in res.stdout


def _pinned_floor_mib(lo: int = 16, hi: int = 1024, step: int = 4) -> int:
    assert _imports(hi, pinned=True), f"pinned numpy import fails even at {hi} MiB"
    while hi - lo > step:
        mid = (lo + hi) // 2
        if _imports(mid, pinned=True):
            hi = mid
        else:
            lo = mid
    return hi


def test_child_env_sets_the_openblas_thread_limit_on_every_platform(tmp_path):
    for platform in ("linux", "darwin", "win32"):
        env = child_env(tmp_path, tmp_path, tmp_path, "trace", 2 * 1024 ** 3,
                        platform=platform, source={})
        assert env["OPENBLAS_NUM_THREADS"] == "1", platform


def test_unpinned_thread_pool_breaks_a_cap_the_pinned_import_fits():
    cpus = _visible_cpus()
    if cpus < 2:
        pytest.skip("one visible CPU: OpenBLAS starts no extra threads, so #38 "
                    "cannot occur on this host")
    cap = _pinned_floor_mib() + 8
    assert _imports(cap, pinned=True)
    assert not _imports(cap, pinned=False), (
        f"with {cpus} visible CPUs the unpinned import fit in {cap} MiB, so this "
        f"host does not exercise #38; the calibration needs revisiting")
    assert _imports(cap + 64 * cpus, pinned=False), (
        "the unpinned import should fit once the cap covers the extra threads")
