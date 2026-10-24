"""Scratch directories for background jobs that must put file content on disk
(videos are too big for memory). Always removed afterwards, success or not."""
from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("cloudclean")

PREFIX = "cloudclean-job-"


def temp_root() -> Path:
    return Path(settings.job_temp_dir or tempfile.gettempdir())


@contextmanager
def job_workdir():
    root = temp_root()
    root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=PREFIX, dir=root))
    try:
        yield path
    finally:
        _remove(path)


def remove_leftovers() -> int:
    """Delete scratch dirs a crashed worker left behind. Call only when no
    other worker is running."""
    leftovers = list(temp_root().glob(PREFIX + "*"))
    for path in leftovers:
        _remove(path)
    return len(leftovers)


def free_bytes() -> int:
    root = temp_root()
    root.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(root).free


def _remove(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        logger.warning("Could not fully remove job scratch directory %s", path)
