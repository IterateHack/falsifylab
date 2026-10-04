"""Put the repo root on sys.path so `import contract` resolves from
scenarios/b_cd5_affinity/auditor/tests/golden/."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
