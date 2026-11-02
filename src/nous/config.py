"""Local app settings; public pages never receive saved credentials."""

import json
import os
import sysconfig
import tempfile
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    return Path(os.getenv("NOUS_DATA_DIR", str(Path.home() / ".config" / "nous")))


def model_dir() -> Path:
    return Path(os.getenv("NOUS_MODEL_PATH", str(data_dir() / "model")))


def user_library_path() -> Path:
    return data_dir() / "concepts.npz"


def bundled_library_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "library" / "nous-fitted.npz"
    if source.is_file():
        return source
    return Path(sysconfig.get_path("data")) / "share" / "nous" / "nous-fitted.npz"


def library_path() -> Path:
    custom = user_library_path()
    return custom if custom.is_file() else bundled_library_path()


def require_model_path(local_path: str | None = None) -> Path:
    location = Path(local_path) if local_path else model_dir()
    if not (location / "config.json").is_file():
        raise FileNotFoundError(
            f"The AI brain is not ready at {location}. Run setup.bat on Windows, "
            "or install nous[model] and run python -m nous.install, then try again. "
            "Use --model-path or NOUS_MODEL_PATH for a different local folder."
        )
    return location


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
