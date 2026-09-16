"""Shared test fixtures: synthetic data only — tests never read a real WHOOP export."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from generate_demo_data import generate  # noqa: E402
import build_dashboard  # noqa: E402


def make_data_dir(days=120, seed=23):
    """A temp dir with a synthetic whoop_data.json and the built dashboard files."""
    d = tempfile.mkdtemp(prefix="whoop-test-")
    with open(os.path.join(d, "whoop_data.json"), "w") as f:
        json.dump(generate(days, seed), f)
    build_dashboard.main(d)
    return d
