import hashlib
import json
import re
from dataclasses import asdict, dataclass
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

    def __post_init__(self) -> None:
        n = len(self.concepts)
        if self.V.ndim != 2 or self.D.shape != self.V.shape or self.V.shape[0] != n:
            raise ValueError("Invalid library vector shapes")
        if self.HR_neutral.shape != (self.V.shape[1],) or self.thresholds.shape != (n,):
            raise ValueError("Invalid library baseline or thresholds")
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
    def hash(self) -> str:
        digest = hashlib.sha256(config_hash(self.config).encode())
        digest.update(json.dumps([asdict(c) for c in self.concepts], sort_keys=True).encode())
        for array in (self.V, self.D, self.HR_neutral, self.thresholds):
            digest.update(np.asarray(array, dtype="<f8").tobytes())
        return digest.hexdigest()

    def defender(self) -> DefendSpec:
        return DefendSpec(self.V, self.thresholds, self.ids)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            V=self.V,
            D=self.D,
            HR_neutral=self.HR_neutral,
            thresholds=self.thresholds,
            V_norms=np.linalg.norm(self.V, axis=1),
            D_norms=np.linalg.norm(self.D, axis=1),
            config=json.dumps(self.config, sort_keys=True),
            config_hash=config_hash(self.config),
            concepts=json.dumps([asdict(c) for c in self.concepts]),
            library_hash=self.hash,
        )

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
            library = cls(
                concepts, data["V"], data["D"], data["HR_neutral"], data["thresholds"], config
            )
            if library.hash != str(data["library_hash"]):
                raise ValueError("Library content hash mismatch")
            return library
