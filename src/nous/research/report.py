"""Stable aggregate artifacts, with no wall-clock values in reproducible tables."""

import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def flattened(row: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result = {}
    for key, value in row.items():
        name = prefix + key
        if isinstance(value, dict):
            result.update(flattened(value, name + "."))
        elif isinstance(value, list):
            result[name] = json.dumps(value, separators=(",", ":"))
        else:
            result[name] = value
    return result


def markdown(rows: list[dict[str, Any]]) -> str:
    flat = [flattened(row) for row in rows]
    keys = sorted({k for row in flat for k in row})

    def cell(value: Any) -> str:
        return (
            str(value if value is not None else "unavailable")
            .replace("|", "\\|")
            .replace("\n", " ")
        )

    return (
        "| "
        + " | ".join(keys)
        + " |\n| "
        + " | ".join("---" for _ in keys)
        + " |\n"
        + "".join("| " + " | ".join(cell(row.get(k, "—")) for k in keys) + " |\n" for row in flat)
    )


def figures(output: Path, tables: dict[str, list[dict[str, Any]]]) -> None:
    os.environ.setdefault(
        "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "nous-research-matplotlib")
    )
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Install nous[research] to render research figures") from exc
    matplotlib.rcParams.update({"svg.hashsalt": "nous-research", "font.family": "DejaVu Sans"})
    specifications = {
        "dose": ("alpha", "keyword_hit", "task_kept"),
        "injection_layer": ("layer", "keyword_hit", "cosine_top1"),
        "vector": ("vector", "keyword_hit", "cosine_top1"),
        "readout_layer": ("readout", "cosine_top1", "cosine_top3"),
        "v4": ("classifier", "top1", "cosine_top1"),
        "immune": ("alpha", "keyword_hit", "task_kept"),
        "alarm": ("percentile", "any_alarm", "attribution"),
        "false_alarms": ("percentile", "any_alarm", "token_alarm"),
        "attribution": ("exempt", "attribution", "any_alarm"),
    }
    folder = output / "figures"
    folder.mkdir(exist_ok=True)
    for name, (axis, *metrics) in specifications.items():
        fig, ax = plt.subplots(figsize=(9, 5), layout="constrained")
        table_name = "alarm" if name in {"false_alarms", "attribution"} else name
        rows = [r for r in tables[table_name] if r["status"] == "run"]
        if name in {"vector", "injection_layer", "readout_layer"}:
            rows = [r for r in rows if r["alpha"] == 0.45]
        if name == "immune":
            rows = [r for r in rows if not r["topical"]]
        if name == "alarm":
            rows = [
                r
                for r in rows
                if r["z"] == 4
                and r["run"] == 8
                and r["exempt"]
                and not r["topical"]
                and r["immune"]
            ]
        if name == "false_alarms":
            rows = [
                r
                for r in rows
                if r["alpha"] == 0
                and r["z"] == 4
                and r["run"] == 8
                and r["immune"]
                and not r["topical"]
            ]
        if name == "attribution":
            rows = [
                r
                for r in rows
                if r["alpha"] == 0.45
                and r["z"] == 4
                and r["run"] == 8
                and r["percentile"] == 99.5
                and r["immune"]
            ]
        if rows:
            x = list(range(len(rows)))
            for metric in metrics:
                usable = [
                    (i, r["metrics"][metric]) for i, r in enumerate(rows) if metric in r["metrics"]
                ]
                ax.errorbar(
                    [i for i, _ in usable],
                    [m["mean"] for _, m in usable],
                    yerr=[
                        [m["mean"] - m["cluster_ci95"][0] for _, m in usable],
                        [m["cluster_ci95"][1] - m["mean"] for _, m in usable],
                    ],
                    fmt="o",
                    capsize=3,
                    label=metric,
                )
            if len(rows) <= 24:
                ax.set_xticks(x, [str(r[axis]) for r in rows], rotation=35)
            ax.legend()
            ax.set_ylabel("Answer rate; concept-cluster interval")
            ax.set_title(f"{name}: actual n per cell in companion table")
        else:
            ax.text(
                0.5,
                0.55,
                "UNRUN — trained local model unavailable",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.text(
                0.5, 0.42, "n = 0; no estimates or intervals", ha="center", transform=ax.transAxes
            )
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(name)
        ax.set_xlabel(axis)
        fig.savefig(folder / f"{name}.png", dpi=150, metadata={"Software": "NOUS research"})
        fig.savefig(folder / f"{name}.svg", metadata={"Date": None, "Creator": "NOUS research"})
        plt.close(fig)
    # ROC uses actual matched neutral/injected detection rates, never a line through absent cells.
    fig, ax = plt.subplots(figsize=(6, 5), layout="constrained")
    alarm = [r for r in tables["alarm"] if r["status"] == "run" and not r["topical"]]
    pairs: dict[tuple[Any, ...], dict[float, dict[str, Any]]] = {}
    for r in alarm:
        key = (r["percentile"], r["z"], r["run"], r["exempt"], r["immune"])
        pairs.setdefault(key, {})[r["alpha"]] = r
    points = [pair for pair in pairs.values() if 0 in pair and 0.45 in pair]
    if points:
        ax.scatter(
            [p[0]["metrics"]["any_alarm"]["mean"] for p in points],
            [p[0.45]["metrics"]["any_alarm"]["mean"] for p in points],
            s=12,
        )
    else:
        ax.text(0.5, 0.5, "UNRUN; n = 0", ha="center", transform=ax.transAxes)
    ax.set(xlabel="Neutral any-alarm rate", ylabel="Injected any-alarm rate", title="Immune ROC")
    fig.savefig(folder / "roc.png", dpi=150)
    fig.savefig(folder / "roc.svg", metadata={"Date": None})
    plt.close(fig)


def write_artifacts(
    output: Path, tables: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]
) -> None:
    folder = output / "tables"
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        (folder / f"{name}.json").write_text(stable_json(rows))
        flat = [flattened(row) for row in rows]
        fields = sorted({k for row in flat for k in row})
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(flat)
        (folder / f"{name}.csv").write_text(buffer.getvalue())
        (folder / f"{name}.md").write_text(markdown(rows))
    figures(output, tables)
    artifacts = sorted(
        p for root in [folder, output / "figures"] for p in root.iterdir() if p.is_file()
    )
    artifacts.extend(
        output / name
        for name in ["selected-readout.npz", "fitted-library.npz", "observations.json"]
        if (output / name).is_file()
    )
    manifest["artifacts"] = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts
    }
    (output / "manifest.json").write_text(stable_json(manifest))
