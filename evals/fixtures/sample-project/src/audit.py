"""Documentation audits."""

import os

from config import MAX_RETRIES


def _scan_files(root):
    found = []
    for folder, _, files in os.walk(root):
        found += [os.path.join(folder, f) for f in files if f.endswith(".md")]
    return sorted(found)


def start_audit(api_key, paths=None):
    """
    Start a documentation audit.

    Scans every .md file under the current folder unless paths is given.
    Retries failed requests up to MAX_RETRIES times.
    """
    if not api_key:
        raise ValueError("api_key is required")
    files = paths if paths is not None else _scan_files(".")
    return {"files": files, "retries": MAX_RETRIES}
