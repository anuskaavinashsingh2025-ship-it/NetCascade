from netcascade import get_topology, simulate_device_failure
from netcascade.simulate import main
from netcascade.visualize import draw_failure, draw_ranking, generate_all, layered_layout


def test_layout_places_servers_on_top_and_pcs_at_bottom():
    pos = layered_layout(get_topology("basic"))
    assert pos["SRV1"][1] > pos["R1"][1] > pos["SW1"][1] > pos["PC1"][1]
    assert pos["PC1"][1] == pos["PC3"][1]


def test_draw_failure_and_ranking(tmp_path):
    net = get_topology("redundant")
    before = net.to_dict()
    out = draw_failure(net, simulate_device_failure(net, "R1"), tmp_path / "f.png")
    rank = draw_ranking(net, tmp_path / "r.png")
    assert out.stat().st_size > 10_000 and rank.stat().st_size > 10_000
    assert net.to_dict() == before


def test_generate_all(tmp_path):
    paths = generate_all(tmp_path)
    assert len(paths) == 9 and all(p.exists() for p in paths)


def test_cli_device(capsys):
    assert main(["basic", "--device", "R1"]) == 0
    out = capsys.readouterr().out
    assert "Critical" in out and "100.00%" in out


def test_cli_link_rank_spof(capsys):
    assert main(["redundant", "--link", "SW1", "R1"]) == 0
    assert main(["redundant", "--rank", "--top", "3"]) == 0
    assert main(["campus", "--spof"]) == 0
    out = capsys.readouterr().out
    assert "Rerouted" in out and "Devices ranked" in out and "DC-SW" in out


def test_cli_invalid_id(capsys):
    assert main(["basic", "--device", "NOPE"]) == 2
    assert "Unknown device" in capsys.readouterr().err


def test_cli_image(tmp_path, capsys):
    img = tmp_path / "x.png"
    assert main(["basic", "--link", "SW1", "R1", "--image", str(img)]) == 0
    assert img.exists()
