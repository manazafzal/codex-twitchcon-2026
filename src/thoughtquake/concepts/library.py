import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from thoughtquake.model.backend import DefendSpec, Vector


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    color_index: int
    aliases: tuple[str, ...]


def load_concepts(path: Path | None = None) -> list[Concept]:
    content = path.read_text() if path else files(__package__).joinpath("concepts.yaml").read_text()
    return [Concept(**{**row, "aliases": tuple(row["aliases"])}) for row in yaml.safe_load(content)]


def match_concept(message: str, concepts: list[Concept]) -> str | None:
    matches = []
    for index, concept in enumerate(concepts):
        pattern = (
            r"(?<!\w)(?:" + "|".join(map(re.escape, (concept.id, *concept.aliases))) + r")(?!\w)"
        )
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            matches.append((match.start(), index, concept.id))
    return min(matches)[2] if matches else None


@dataclass
class ConceptLibrary:
    concepts: list[Concept]
    V: Vector
    D: Vector
    HR_neutral: Vector
    thresholds: Vector
    config: dict[str, Any]
    readout_mean: Vector | None = None
    readout_std: Vector | None = None
    alarm_thresholds: Vector | None = None
    readout_v4: dict[str, Vector] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.concepts)
        if self.V.ndim != 2 or self.D.shape != self.V.shape or self.V.shape[0] != n:
            raise ValueError("Invalid library vector shapes")
        if self.HR_neutral.shape != (self.V.shape[1],) or self.thresholds.shape != (n,):
            raise ValueError("Invalid library baseline or thresholds")
        if (self.readout_mean is None) != (self.readout_std is None):
            raise ValueError("Incomplete readout calibration")
        if self.readout_mean is not None:
            assert self.readout_std is not None
            if self.readout_mean.shape != (n,) or self.readout_std.shape != (n,):
                raise ValueError("Invalid readout calibration shapes")
            if (
                not np.isfinite(self.readout_mean).all()
                or not np.isfinite(self.readout_std).all()
                or np.any(self.readout_std <= 0)
            ):
                raise ValueError("Invalid readout calibration")
        if self.alarm_thresholds is not None and (
            self.alarm_thresholds.shape != (n,) or not np.isfinite(self.alarm_thresholds).all()
        ):
            raise ValueError("Invalid alarm thresholds")
        if self.readout_v4:
            required = {"center", "scale", "weights", "intercept", "shrinkage"}
            if set(self.readout_v4) != required or self.readout_v4["weights"].shape[0] != n:
                raise ValueError("Invalid v4 arrays")
            width = self.readout_v4["center"].size
            if (
                "probe_layers" in self.config
                and width != len(self.config["probe_layers"]) * self.V.shape[1]
            ):
                raise ValueError("Invalid multi-layer width")
            if (
                self.readout_v4["scale"].shape != (width,)
                or self.readout_v4["weights"].shape != (n, width)
                or self.readout_v4["intercept"].shape != (n,)
            ):
                raise ValueError("Invalid v4 shapes")
            if any(not np.isfinite(a).all() for a in self.readout_v4.values()) or np.any(
                self.readout_v4["scale"] <= 0
            ):
                raise ValueError("Invalid v4 values")
        if len(set(self.ids)) != n:
            raise ValueError("Duplicate concept ids")
        if not all(
            np.isfinite(x).all() for x in (self.V, self.D, self.HR_neutral, self.thresholds)
        ):
            raise ValueError("Non-finite library data")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.concepts)

    @property
    def variant(self) -> str:
        return str(self.config.get("variant", "neutral"))

    @property
    def median_residual_norm(self) -> float:
        return float(self.config.get("median_residual_norm", 26.78))

    @property
    def vector_hashes(self) -> dict[str, str]:
        return {
            key: hashlib.sha256(np.asarray([v, d], dtype="<f8").tobytes()).hexdigest()
            for key, v, d in zip(self.ids, self.V, self.D, strict=True)
        }

    def arrays(self) -> dict[str, Vector]:
        result = {
            "V": self.V,
            "D": self.D,
            "HR_neutral": self.HR_neutral,
            "thresholds": self.thresholds,
            "V_norms": np.linalg.norm(self.V, axis=1),
            "D_norms": np.linalg.norm(self.D, axis=1),
        }
        for name in ("readout_mean", "readout_std", "alarm_thresholds"):
            value = getattr(self, name)
            result[name] = value if value is not None else np.array([])
        result.update({"v4_" + key: value for key, value in self.readout_v4.items()})
        return result

    @property
    def hash(self) -> str:
        digest = hashlib.sha256(config_hash(self.config).encode())
        digest.update(json.dumps([asdict(c) for c in self.concepts], sort_keys=True).encode())
        digest.update(json.dumps(self.provenance, sort_keys=True).encode())
        for name, array in sorted(self.arrays().items()):
            value = np.asarray(array, dtype="<f8")
            digest.update(name.encode())
            digest.update(str(value.shape).encode())
            digest.update(value.tobytes())
        return digest.hexdigest()

    def layout(self) -> dict[str, list[float]]:
        from thoughtquake.engine.atlas import pca_points
        from thoughtquake.engine.immune import unit

        return pca_points(unit(self.D), self.ids)

    def mentioned_in(self, text: str) -> set[str]:
        return {c.id for c in self.concepts if concept_pattern(c, stems=True).search(text)}

    def defender(self) -> DefendSpec:
        return DefendSpec(self.V, self.thresholds, self.ids)

    def save(self, path: Path) -> None:
        import os
        import tempfile

        self.__post_init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "config": json.dumps(self.config, sort_keys=True),
            "config_hash": config_hash(self.config),
            "concepts": json.dumps([asdict(c) for c in self.concepts]),
            "provenance": json.dumps(self.provenance, sort_keys=True),
            "vector_hashes": json.dumps(self.vector_hashes, sort_keys=True),
            "library_hash": self.hash,
            "schema": "2",
        }
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".npz")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                payload: dict[str, Any] = {**self.arrays(), **metadata}
                np.savez_compressed(handle, **payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: Path, expected_config: dict[str, Any] | None = None) -> "ConceptLibrary":
        with np.load(path, allow_pickle=False) as data:
            config = json.loads(str(data["config"]))
            if str(data["config_hash"]) != config_hash(config):
                raise ValueError("Library config hash mismatch")
            if expected_config is not None and config_hash(expected_config) != config_hash(config):
                raise ValueError("Library does not match requested config")
            concepts = [
                Concept(**{**c, "aliases": tuple(c["aliases"])})
                for c in json.loads(str(data["concepts"]))
            ]
            optional = {
                name: data[name] if name in data and data[name].size else None
                for name in ("readout_mean", "readout_std", "alarm_thresholds")
            }
            probe = {key[3:]: data[key] for key in data.files if key.startswith("v4_")}
            library = cls(
                concepts,
                data["V"],
                data["D"],
                data["HR_neutral"],
                data["thresholds"],
                config,
                **optional,
                readout_v4=probe,
                provenance=json.loads(str(data["provenance"])) if "provenance" in data else {},
            )
            if "schema" in data:
                if str(data["schema"]) != "2":
                    raise ValueError("Library content hash mismatch")
                expected = set(library.arrays()) | {
                    "config",
                    "config_hash",
                    "concepts",
                    "provenance",
                    "vector_hashes",
                    "library_hash",
                    "schema",
                }
                if set(data.files) != expected or any(
                    not np.array_equal(data[key], value) for key, value in library.arrays().items()
                ):
                    raise ValueError("Library content hash mismatch")
                valid = library.hash == str(
                    data["library_hash"]
                ) and library.vector_hashes == json.loads(str(data["vector_hashes"]))
            else:
                # Retain the old checksum algorithm only when importing an older file.
                digest = hashlib.sha256(config_hash(config).encode())
                digest.update(json.dumps([asdict(c) for c in concepts], sort_keys=True).encode())
                arrays = [library.V, library.D, library.HR_neutral, library.thresholds]
                if library.readout_mean is not None:
                    assert library.readout_std is not None
                    arrays += [library.readout_mean, library.readout_std]
                for array in arrays:
                    digest.update(np.asarray(array, dtype="<f8").tobytes())
                valid = digest.hexdigest() == str(data["library_hash"])
            if not valid:
                raise ValueError("Library content hash mismatch")
            return library


def concept_pattern(concept: Concept, *, stems: bool = False) -> re.Pattern[str]:
    words = (concept.id.replace("-", " "), concept.id, concept.label, *concept.aliases)
    alternatives: list[str] = []
    for word in words:
        base = word.casefold()
        roots = {base}
        if stems and len(base) >= 3:
            for suffix in ("ing", "ies", "es", "s", "ed"):
                if base.endswith(suffix) and len(base) - len(suffix) >= 3:
                    roots.add(base[: -len(suffix)])
            if len(base) > 3 and base.endswith("e"):
                roots.add(base[:-1])
            if len(base) > 4 and base.endswith("y"):
                roots.add(base[:-1])
            ending = r"(?:s|es|ed|ing|y|ies|ic|ical|al|er|ers|ier|like)?"
        else:
            ending = ""
        alternatives.extend(
            re.escape(root) + ending
            for root in sorted(roots, key=lambda value: (-len(value), value))
        )
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE)
