import os
import subprocess

_VERSION_FILE = os.path.join(os.path.dirname(__file__), "..", "VERSION")


def get_version() -> str:
    """Retorna versão no formato '1.0.0 (abc1234)' usando VERSION + git hash."""
    try:
        with open(_VERSION_FILE) as f:
            ver = f.read().strip()
    except OSError:
        ver = "?.?.?"

    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(_VERSION_FILE),
        ).decode().strip()
        return f"{ver} ({git_hash})"
    except Exception:
        return ver
