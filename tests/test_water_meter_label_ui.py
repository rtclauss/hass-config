from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from water_meter import label_ui
from water_meter.labels import LabelStore

TOKEN = "s3cret-token"
CAPTURE = "20260929T100000Z"


@pytest.fixture()
def server(tmp_path: Path):
    history = tmp_path / "images" / "history"
    history.mkdir(parents=True)
    (history / f"{CAPTURE}_crop.jpg").write_bytes(b"\xff\xd8crop")
    (history / f"{CAPTURE}_raw.jpg").write_bytes(b"\xff\xd8raw")
    (history / f"{CAPTURE}_read.json").write_text(
        json.dumps({"raw_digits": "02147013", "accepted": False, "reason": "value decreased"})
    )
    store = LabelStore(tmp_path / "images", tmp_path / "state")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), label_ui.make_handler(store, TOKEN))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_port, store, tmp_path
    httpd.shutdown()
    thread.join(timeout=2)


def _request(port: int, method: str, path: str, *, cookie: bool = True, body: dict | None = None,
             headers: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdrs = dict(headers or {})
    if cookie:
        hdrs["Cookie"] = f"{label_ui.COOKIE_NAME}={TOKEN}"
    data = None
    if body is not None:
        data = json.dumps(body)
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    response = conn.getresponse()
    payload = response.read()
    return response.status, dict(response.getheaders()), payload


def test_everything_requires_auth(server) -> None:
    port, _, _ = server
    for path in ("/", "/api/queue", "/api/item?id=" + CAPTURE, "/api/stats", f"/img?id={CAPTURE}&name=crop"):
        status, _, _ = _request(port, "GET", path, cookie=False)
        assert status == 401, path
    status, _, _ = _request(port, "POST", "/api/label", cookie=False, body={"capture_id": CAPTURE, "kind": "reading", "value": "02147013"})
    assert status == 401


def test_token_query_sets_a_cookie_and_redirects_without_the_secret(server) -> None:
    port, _, _ = server
    status, headers, _ = _request(port, "GET", f"/?token={TOKEN}&item={CAPTURE}", cookie=False)
    assert status == 302
    assert headers["Location"] == f"/?item={CAPTURE}"
    assert TOKEN not in headers["Location"]
    assert f"{label_ui.COOKIE_NAME}={TOKEN}" in headers["Set-Cookie"]
    assert "HttpOnly" in headers["Set-Cookie"]

    status, _, _ = _request(port, "GET", "/?token=wrong", cookie=False)
    assert status == 401


def test_bearer_header_also_authenticates(server) -> None:
    port, _, _ = server
    status, _, _ = _request(port, "GET", "/api/stats", cookie=False, headers={"Authorization": f"Bearer {TOKEN}"})
    assert status == 200


def test_page_is_mobile_friendly_single_page_app(server) -> None:
    port, _, _ = server
    status, headers, body = _request(port, "GET", "/")
    html = body.decode()
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert 'name="viewport"' in html and "width=device-width" in html
    assert 'id="keypad"' in html  # on-screen keypad for touch
    assert "@media (max-width:520px)" in html  # narrow-screen layout
    assert "min-height:52px" in html  # >= 44px touch targets
    assert "__DIGITS__" not in html
    assert "https://" not in html.replace("https://www.w3.org", "")  # no CDN/external assets


def test_queue_item_and_label_round_trip(server) -> None:
    port, store, _ = server
    status, _, body = _request(port, "GET", "/api/queue?mode=queue")
    queue = json.loads(body)
    assert status == 200 and queue["depth"] == 1
    assert queue["items"][0]["id"] == CAPTURE and queue["items"][0]["rejected"] is True

    status, _, body = _request(port, "POST", "/api/label", body={"capture_id": CAPTURE, "kind": "reading", "value": "02147013"})
    assert status == 200
    item = json.loads(body)
    assert item["labels"]["reading"] == "02147013" and item["status"] == "labeled" and item["split"]

    assert json.loads(_request(port, "GET", "/api/queue?mode=queue")[2])["depth"] == 0
    assert json.loads(_request(port, "GET", "/api/queue?mode=labeled")[2])["depth"] == 1
    stats = json.loads(_request(port, "GET", "/api/stats")[2])
    assert stats["labeled"] == 1 and stats["coverage"][4][7] == 1


def test_bad_label_requests_are_rejected(server) -> None:
    port, _, _ = server
    for body in (
        {"capture_id": CAPTURE, "kind": "reading", "value": "123"},
        {"capture_id": "../../etc/passwd", "kind": "reading", "value": "02147013"},
        {"capture_id": CAPTURE, "kind": "digit", "position": 99, "value": "1"},
        {"capture_id": CAPTURE, "kind": "nope"},
        {"kind": "reading"},
    ):
        status, _, _ = _request(port, "POST", "/api/label", body=body)
        assert status == 400, body
    status, _, _ = _request(port, "GET", "/api/item?id=20200101T000000Z")
    assert status == 404


def test_images_are_served_only_for_valid_ids_and_names(server) -> None:
    port, _, _ = server
    status, headers, body = _request(port, "GET", f"/img?id={CAPTURE}&name=crop")
    assert status == 200 and headers["Content-Type"] == "image/jpeg" and body.startswith(b"\xff\xd8")
    for path in (
        f"/img?id={CAPTURE}&name=../../state/labels",
        f"/img?id=../images&name=crop",
        f"/img?id={CAPTURE}&name=digit3",  # valid name, file absent
        "/img",
    ):
        status, _, _ = _request(port, "GET", path)
        assert status == 404, path


def test_blind_mode_is_enforced_server_side(server) -> None:
    port, _, _ = server
    item = json.loads(_request(port, "GET", f"/api/item?id={CAPTURE}")[2])
    assert item["guess"] == "02147013"
    blind = json.loads(_request(port, "GET", f"/api/item?id={CAPTURE}&blind=1")[2])
    assert blind["guess"] is None and blind["reason"] is None
    q = json.loads(_request(port, "GET", "/api/queue?blind=1")[2])["items"][0]
    assert q["guess"] is None


def test_oversized_bodies_are_rejected(server) -> None:
    port, _, _ = server
    status, _, _ = _request(port, "POST", "/api/label", body={"capture_id": CAPTURE, "kind": "flag", "flag": "unreadable", "pad": "x" * 5000})
    assert status == 400


def test_main_refuses_to_serve_without_a_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WATER_METER_LABEL_UI_TOKEN", raising=False)
    monkeypatch.delenv("WATER_METER_CORRECTION_TOKEN", raising=False)
    monkeypatch.setenv("WATER_METER_IMAGE_DIR", str(tmp_path / "i"))
    monkeypatch.setenv("WATER_METER_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("WATER_METER_CALIBRATION_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr("sys.argv", ["label_ui"])
    with pytest.raises(SystemExit):
        label_ui.main()


def _calibration_json() -> dict:
    boxes = [[100 + 25 * i, 40, 24, 40] for i in range(8)]
    return {
        "roi": [90, 30, 250, 60],
        "digit_boxes": boxes,
        "digit_count": 8,
        "ssocr_args": ["-d", "8"],
        "decimal_places": 1,
        "capture_width": 1280,
        "capture_height": 960,
        "rotation_degrees": 0.0,
    }


@pytest.fixture()
def cal_server(tmp_path: Path):
    tmp_path = tmp_path / "cal"
    history = tmp_path / "images" / "history"
    history.mkdir(parents=True)
    (history / f"{CAPTURE}_crop.jpg").write_bytes(b"\xff\xd8crop")
    cal_path = tmp_path / "calibration.json"
    cal_path.write_text(json.dumps(_calibration_json()))
    store = LabelStore(tmp_path / "images", tmp_path / "state", calibration_path=cal_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), label_ui.make_handler(store, TOKEN))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_port, cal_path
    httpd.shutdown()
    thread.join(timeout=2)


def test_calibration_get_requires_auth_and_a_file(server, cal_server) -> None:
    port, _, _ = server
    assert _request(port, "GET", "/api/calibration", cookie=False)[0] == 401
    assert _request(port, "GET", "/api/calibration")[0] == 404  # this server has no calibration file
    cal_port, _ = cal_server
    status, _, body = _request(cal_port, "GET", "/api/calibration")
    data = json.loads(body)
    assert status == 200 and len(data["digit_boxes"]) == 8 and data["rotation_degrees"] == 0.0
    assert data["capture_width"] == 1280


def test_calibration_save_updates_boxes_and_rotation_keeps_the_rest_and_backs_up(cal_server) -> None:
    port, cal_path = cal_server
    boxes = [[90 + 26 * i, 36, 28, 44] for i in range(8)]
    status, _, body = _request(port, "POST", "/api/calibration", body={"digit_boxes": boxes, "rotation_degrees": -2})
    assert status == 200 and json.loads(body)["rotation_degrees"] == -2.0

    saved = json.loads(cal_path.read_text())
    assert saved["digit_boxes"] == boxes and saved["rotation_degrees"] == -2.0
    assert saved["ssocr_args"] == ["-d", "8"] and saved["decimal_places"] == 1  # untouched
    assert saved["capture_width"] == 1280
    backups = list(cal_path.parent.glob("calibration.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["rotation_degrees"] == 0.0  # the previous file


@pytest.mark.parametrize(
    "body",
    [
        {"digit_boxes": [[0, 0, 10, 10]] * 7},  # wrong count
        {"digit_boxes": [[1270, 0, 30, 10]] * 8},  # past the frame edge
        {"digit_boxes": [[0, 0, 2, 2]] * 8},  # degenerate
        {"digit_boxes": [[0, 0, 10.5, 10]] * 8},  # not integers
        {"digit_boxes": [[True, 0, 10, 10]] * 8},  # bools are not ints here
        {"rotation_degrees": 30},
        {"rotation_degrees": "2"},
        {"digit_boxes": "nope"},
        {"roi": [0, 0, 5000, 10]},
    ],
)
def test_calibration_save_rejects_bad_edits_without_touching_the_file(cal_server, body) -> None:
    port, cal_path = cal_server
    before = cal_path.read_text()
    status, _, _ = _request(port, "POST", "/api/calibration", body=body)
    assert status == 400
    assert cal_path.read_text() == before
    assert not list(cal_path.parent.glob("calibration.json.bak.*"))


def test_calibration_save_requires_auth(cal_server) -> None:
    port, cal_path = cal_server
    status, _, _ = _request(port, "POST", "/api/calibration", cookie=False, body={"rotation_degrees": 1})
    assert status == 401
    assert json.loads(cal_path.read_text())["rotation_degrees"] == 0.0


def test_page_has_rotation_box_editor_and_reject_frame_controls(server) -> None:
    port, _, _ = server
    html = _request(port, "GET", "/")[2].decode()
    for marker in ('id="rotM"', 'id="rotP"', 'id="boxCanvas"', 'id="boxSave"', 'id="fBad"', "counter-clockwise",
                   'value="excluded"', "may be cut off"):
        assert marker in html, marker


def test_bad_frames_leave_the_queue_and_can_be_restored(server) -> None:
    port, store, _ = server
    body = {"capture_id": CAPTURE, "kind": "flag", "flag": "bad_frame", "value": True}
    status, _, resp = _request(port, "POST", "/api/label", body=body)
    assert status == 200 and json.loads(resp)["status"] == "excluded"

    assert json.loads(_request(port, "GET", "/api/queue?mode=queue")[2])["depth"] == 0
    excluded = json.loads(_request(port, "GET", "/api/queue?mode=excluded")[2])
    assert [i["id"] for i in excluded["items"]] == [CAPTURE]
    stats = json.loads(_request(port, "GET", "/api/stats")[2])
    assert stats["excluded"] == 1 and stats["unlabeled"] == 0

    _request(port, "POST", "/api/label", body={**body, "value": False})
    assert json.loads(_request(port, "GET", "/api/queue?mode=queue")[2])["depth"] == 1


def test_editor_pivots_rotation_on_the_roi_like_the_reader(server) -> None:
    # Rotating about the far-away frame centre mostly slides the display
    # (about 6 px per degree) instead of tilting it; the reader and the editor
    # must both pivot on the ROI centre or the preview lies about what is cut.
    port, _, _ = server
    html = _request(port, "GET", "/")[2].decode()
    assert "px = r[0]+r[2]/2, py = r[1]+r[3]/2" in html
    assert "c.translate(px, py)" in html
