import pytest

from src.tools import charts
from src.tools.registry import create_chart


@pytest.fixture(autouse=True)
def chart_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(charts, "_DIR", tmp_path / "charts")
    return tmp_path / "charts"


def test_it_writes_a_real_png(chart_dir):
    path = charts.render("Monthly revenue", "line", ["Jan", "Feb"], {"2026": [1.0, 1.4]}, "USD")
    written = chart_dir / path.rsplit("/", 1)[-1]
    assert written.exists()
    assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("kind", ["bar", "line", "barh"])
def test_every_supported_kind_renders(kind):
    assert charts.render("t", kind, ["a", "b"], {"s": [1.0, 2.0]}).endswith(".png")


def test_a_grouped_series_renders(chart_dir):
    charts.render("t", "bar", ["x"], {"Texas": [1.0], "California": [2.0]})
    assert len(list(chart_dir.glob("*.png"))) == 1


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"kind": "pie"}, "kind must be one of"),
        ({"labels": []}, "at least one label"),
        ({"series": {"s": [1.0, 2.0, 3.0]}}, "has 3 values for 2 labels"),
        ({"labels": [str(i) for i in range(41)]}, "at most 40 points"),
        ({"series": {str(i): [1.0, 2.0] for i in range(7)}}, "at most 6 series"),
    ],
)
def test_bad_input_is_rejected(kwargs, message):
    call = {"title": "t", "kind": "bar", "labels": ["a", "b"], "series": {"s": [1.0, 2.0]}} | kwargs
    with pytest.raises(ValueError, match=message):
        charts.render(**call)


def test_labels_are_scrubbed_before_they_reach_the_image(monkeypatch):
    captured = []
    original = charts.plt.subplots

    def spy(*args, **kwargs):
        figure, axes = original(*args, **kwargs)
        captured.append(axes)
        return figure, axes

    monkeypatch.setattr(charts.plt, "subplots", spy)
    charts.render("mail ops@shop.com", "bar", ["ops@shop.com"], {"s": [1.0]})
    assert "[REDACTED_EMAIL]" in captured[0].get_title()
    assert all("@" not in label.get_text() for label in captured[0].get_xticklabels())


def test_the_tool_reports_bad_input_instead_of_raising():
    result = create_chart.invoke(
        {"title": "t", "kind": "pie", "labels": ["a"], "series": {"s": [1.0]}}
    )
    assert result.startswith("Chart not created:") and "kind must be one of" in result


def test_the_tool_returns_the_path_for_the_manager():
    result = create_chart.invoke(
        {"title": "Revenue", "kind": "line", "labels": ["Jan", "Feb"], "series": {"s": [1.0, 2.0]}}
    )
    assert "Chart saved to" in result and result.count(".png") == 1
