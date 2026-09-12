import re
import uuid
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from src.agent import memory
from src.utils.config import settings
from src.utils.logger import event
from src.utils.pii import scrub

_DIR = settings.data_dir / "charts"
KINDS = ("bar", "line", "barh")
MAX_SERIES = 6
MAX_POINTS = 40


def render(title: str, kind: str, labels: list[str], series: dict[str, list[float]], value_label: str = "") -> str:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not labels or not series:
        raise ValueError("a chart needs at least one label and one series")
    if len(series) > MAX_SERIES:
        raise ValueError(f"at most {MAX_SERIES} series")
    if len(labels) > MAX_POINTS:
        raise ValueError(f"at most {MAX_POINTS} points; aggregate first")
    for name, values in series.items():
        if len(values) != len(labels):
            raise ValueError(f"series {name!r} has {len(values)} values for {len(labels)} labels")

    labels = [scrub(str(label)) for label in labels]
    title = scrub(title)
    _DIR.mkdir(parents=True, exist_ok=True)
    if kind == "barh":
        size = (9.0, max(3.2, min(12.0, 1.6 + 0.55 * len(labels))))
    else:
        size = (max(6.0, min(16.0, 1.0 + 0.62 * len(labels))), 4.8)
    figure, axes = plt.subplots(figsize=size, dpi=140)
    span = range(len(labels))

    if kind == "line":
        for name, values in series.items():
            axes.plot(span, values, marker="o", linewidth=2, label=scrub(name))
        axes.set_xticks(list(span))
        axes.set_xticklabels(labels, rotation=45 if len(labels) > 6 else 0, ha="right" if len(labels) > 6 else "center")
    else:
        step = 0.8 / len(series)
        for index, (name, values) in enumerate(series.items()):
            offset = [point + index * step - 0.4 + step / 2 for point in span]
            plot = axes.barh if kind == "barh" else axes.bar
            plot(offset, values, step * 0.92, label=scrub(name))
        ticks = axes.set_yticks if kind == "barh" else axes.set_xticks
        tick_labels = axes.set_yticklabels if kind == "barh" else axes.set_xticklabels
        ticks(list(span))
        tick_labels(labels, rotation=45 if kind == "bar" and len(labels) > 6 else 0, ha="right" if kind == "bar" and len(labels) > 6 else "center")

    if kind == "barh":
        axes.invert_yaxis()
    value_axis = axes.xaxis if kind == "barh" else axes.yaxis
    if max(abs(value) for values in series.values() for value in values) >= 1000:
        value_axis.set_major_formatter("{x:,.0f}")
        axes.locator_params(axis="x" if kind == "barh" else "y", nbins=6)

    axes.set_title(title, fontsize=12, weight="bold")
    if value_label:
        (axes.set_xlabel if kind == "barh" else axes.set_ylabel)(scrub(value_label))
    if len(series) > 1:
        axes.legend(frameon=False, fontsize=9)
    axes.spines[["top", "right"]].set_visible(False)
    axes.grid(axis="x" if kind == "barh" else "y", alpha=0.25, linewidth=0.6)
    figure.tight_layout()

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "chart"
    path = _DIR / f"{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6]}-{slug}.png"
    figure.savefig(path)
    plt.close(figure)
    event("chart_created", user=memory.active_user.get(), path=str(path), kind=kind, series=list(series), points=len(labels))
    return str(path)
