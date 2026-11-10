from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghostlight.config import Config, load_config  # noqa: E402
from ghostlight.db import Database  # noqa: E402


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    config = load_config(tmp_path / "config.yaml")
    config.set("data_dir", str(tmp_path / "data"))
    return config


@pytest.fixture()
def db(cfg: Config) -> Database:
    return Database(cfg.db_path)
