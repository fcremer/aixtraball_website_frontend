import importlib

import pytest
import yaml

backend = importlib.import_module("app.app")


@pytest.fixture
def slides(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(backend, "YAML_CACHE", {})
    data = [{"image": "first.jpg"}, {"image": "random.jpg"},
            {"image": "pinned.jpg", "pinned": True},
            {"image": "last.jpg", "pinned": "True"},
            {"image": "random2.jpg", "pinned": "False"}]
    (tmp_path / "slides.yaml").write_text(yaml.safe_dump(data))
    return tmp_path / "slides.yaml"


def test_move_first_preserves_fixed_group_and_random_slides(slides):
    with backend.app.test_client() as client:
        with client.session_transaction() as session:
            session["logged_in"] = True
        response = client.post("/admin/slides/0/move", data={"direction": "down"})
        assert response.status_code == 302
        data = yaml.safe_load(slides.read_text())
        assert [s["image"] for s in data] == ["pinned.jpg", "random.jpg", "first.jpg", "last.jpg", "random2.jpg"]
        assert data[2]["pinned"] is True
        prepared = backend.prepare_slides()
        assert [s["image"] for s in prepared[:3]] == ["pinned.jpg", "first.jpg", "last.jpg"]
        assert {s["image"] for s in prepared[3:]} == {"random.jpg", "random2.jpg"}
        html = client.get("/admin/manage/slides.yaml").get_data(as_text=True)
        assert "Feste Position 1" in html
        assert html.index("first.jpg") < html.index("random.jpg")
        assert "/admin/manage/slides.yaml/2" in html


@pytest.mark.parametrize("index,direction", [(0, "up"), (3, "down"), (1, "up"), (0, "invalid")])
def test_invalid_moves_leave_file_unchanged(slides, index, direction):
    before = slides.read_bytes()
    with backend.app.test_client() as client:
        with client.session_transaction() as session:
            session["logged_in"] = True
        assert client.post(f"/admin/slides/{index}/move", data={"direction": direction}).status_code == 400
    assert slides.read_bytes() == before


def test_move_requires_login(slides):
    before = slides.read_bytes()
    with backend.app.test_client() as client:
        assert client.post("/admin/slides/0/move", data={"direction": "down"}).status_code == 302
    assert slides.read_bytes() == before
