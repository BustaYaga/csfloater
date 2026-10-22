import pytest

import app as app_module

H = {"X-Requested-With": "csfloater"}


@pytest.fixture()
def client():
    return app_module.app.test_client()


def test_dashboard_and_dataset(client):
    assert client.get("/").status_code == 200
    d = client.get("/api/dataset").get_json()
    assert d["demo_mode"] and d["public_mode"] and not d["scanner_enabled"]
    assert d["overview"]["items"] > 100 and d["overview"]["items_ready"] > 0
    assert len(client.get("/api/deals").get_json()) > 0


def test_demo_never_uses_api_key():
    assert app_module.CONFIG["csfloat_api_key"] is None
    assert app_module.scanner is None


def test_writes_are_refused(client):
    assert client.post("/api/clear", headers=H).status_code == 403
    assert client.post("/api/scan-now", headers=H).status_code == 403
    assert len(client.get("/api/deals").get_json()) > 0


def test_post_requires_csrf_header(client):
    assert client.post("/api/clear").status_code == 403


def test_host_header_allowlist(client):
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_security_headers(client):
    h = client.get("/").headers
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"


def test_no_third_party_requests_in_template():
    html = open("templates/index.html", encoding="utf-8").read()
    assert "fonts.googleapis" not in html and "<link" not in html and "src=\"http" not in html


def test_listing_id_validation():
    from scanner import LISTING_ID_RE
    assert LISTING_ID_RE.match("abc-123_X")
    assert not LISTING_ID_RE.match('x"><script>') and not LISTING_ID_RE.match("../../etc")
