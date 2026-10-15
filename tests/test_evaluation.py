import csv
import json

import pytest

from netcascade import NetworkGraph, ValidationError, get_topology, rank_devices, rank_links
from netcascade.evaluate import main
from netcascade.evaluation import compare_topologies, component_records, evaluate_topology, failure_stats, timed
from netcascade.simulation import simulate_device_failure


def test_timed_returns_result_and_positive_median():
    result, ms = timed(simulate_device_failure, get_topology("basic"), "R1", repeat=3)
    assert result.impact_score == 100.0 and ms > 0


@pytest.mark.parametrize("repeat", [0, -1, 1.5])
def test_timed_rejects_bad_repeat(repeat):
    with pytest.raises(ValidationError):
        timed(simulate_device_failure, get_topology("basic"), "R1", repeat=repeat)


def test_component_records_match_rankings():
    net = get_topology("redundant")
    records = component_records(net, repeat=1)
    assert len(records) == net.device_count + net.link_count
    expected = {r.label: r.impact_score for r in rank_devices(net) + rank_links(net)}
    assert {r.label: r.impact_score for r in records} == expected
    assert all(r.execution_ms > 0 for r in records)


def test_failure_stats_empty_and_values():
    assert failure_stats([])["count"] == 0
    stats = evaluate_topology(get_topology("basic"), repeat=1)
    dev, link = stats["device_failures"], stats["link_failures"]
    assert dev["count"] == 6 and link["count"] == 5
    assert dev["mean_impact"] == pytest.approx((100 * 3 + 33.33 * 3) / 6, abs=0.01)
    assert link["single_points_of_failure"] == 5 and link["spof_share"] == 100.0
    assert dev["severity_counts"] == {"Low": 0, "Medium": 3, "High": 0, "Critical": 3}


def test_evaluate_topology_shape_and_untouched():
    net = get_topology("campus")
    before = net.to_dict()
    report = evaluate_topology(net, repeat=1)
    assert net.to_dict() == before
    assert (report["devices"], report["links"], report["clients"], report["servers"]) == (23, 34, 8, 3)
    assert report["timing"]["repeat"] == 1 and report["timing"]["full_ranking_ms"] > 0
    assert set(report["single_points_of_failure"]["devices"]) >= {"DC-SW", "ACC-A1"}


def test_empty_topology():
    report = evaluate_topology(NetworkGraph("empty"), repeat=1)
    assert report["all_failures"]["count"] == 0 and report["records"] == []


def test_redundancy_lowers_impact():
    report = compare_topologies(["basic", "redundant"], repeat=1)
    basic, redundant = report["topologies"]
    assert redundant["all_failures"]["mean_impact"] < basic["all_failures"]["mean_impact"]
    assert redundant["all_failures"]["spof_share"] < basic["all_failures"]["spof_share"]
    common = {c["label"]: c["impact"] for c in report["common_failures"]}
    assert common["R1"]["basic"]["impact_score"] == 100.0 and common["R1"]["redundant"]["impact_score"] == 0.0
    link = next(c for c in report["common_failures"] if c["kind"] == "link" and set(c["label"].split("--")) == {"SW1", "R1"})
    assert link["impact"]["redundant"]["single_point_of_failure"] is False


def test_compare_requires_topologies():
    with pytest.raises(ValidationError):
        compare_topologies([], repeat=1)


def test_cli_writes_report(tmp_path, capsys):
    out, img = tmp_path / "results", tmp_path / "images"
    assert main(["basic", "redundant", "--repeat", "2", "--out", str(out), "--images", str(img)]) == 0
    printed = capsys.readouterr().out
    assert "Mean ms" in printed and "* = single point of failure" in printed
    data = json.loads((out / "evaluation.json").read_text())
    assert [t["name"] for t in data["topologies"]] == ["basic", "redundant"] and data["repeat"] == 2
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert len(rows) == 6 and {r["failure_type"] for r in rows} == {"device", "link", "all"}
    assert len(list(csv.DictReader((out / "components.csv").open()))) == 11 + 24
    assert (img / "evaluation_summary.png").stat().st_size > 10_000
    assert (img / "evaluation_common_failures.png").exists()


def test_cli_rejects_bad_repeat(tmp_path):
    with pytest.raises(SystemExit):
        main(["--repeat", "0", "--out", str(tmp_path)])
