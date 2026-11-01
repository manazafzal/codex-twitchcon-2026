"""Local app settings; public pages never receive saved credentials."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    return Path(os.getenv("NOUS_DATA_DIR", str(Path.home() / ".config" / "nous")))


def model_dir() -> Path:
    return Path(os.getenv("NOUS_MODEL_PATH", str(data_dir() / "model")))


def library_path() -> Path:
    return data_dir() / "concepts.npz"


def settings() -> dict[str, Any]:
    try:
        return json.loads((data_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        return {}


def save_settings(values: dict[str, Any]) -> None:
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, directory / "settings.json")
    finally:
        Path(name).unlink(missing_ok=True)
