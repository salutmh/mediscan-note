"""
케이스 자산(의료영상·기준 마스크) 접근 제어.

==========================================================================
**실제로 열려 있었다.**
==========================================================================
`/static/cases/<case_id>/slices/slice_035.png` 를 로그인 없이 받을 수 있었다.
`case_id` 가 `VS-SEG-202` 처럼 예측 가능해서 누구나 열거해 받아갈 수 있었고,
Closed Beta 는 URL 이 외부에 나가므로 실제 문제였다.

`<img src>` 에는 Authorization 헤더를 붙일 수 없어서, URL 자체에 유효기간이 있는
서명을 넣었다. 이 테스트가 무너지면 **인증 없이 의료영상이 다시 나간다.**
"""
import time
from urllib.parse import parse_qs, urlparse

import pytest

from app import asset_urls
from tests.conftest import CASE_ID


def _path_and_query(url: str):
    parsed = urlparse(url)
    return parsed.path, parse_qs(parsed.query)


# ------------------------------------------------------ 실제 차단되는가
def test_unsigned_case_asset_is_forbidden(client):
    """**이 테스트가 무너지면 인증 없이 의료영상이 나간다.**"""
    res = client.get(f"/static/cases/{CASE_ID}/slices/slice_035.png")
    assert res.status_code == 403
    assert res.json()["code"] == "ASSET_URL_UNSIGNED"


def test_tampered_signature_is_forbidden(client):
    expires = int(time.time()) + 3600
    path = f"/static/cases/{CASE_ID}/thumb.png"
    good = asset_urls.sign(path, expires)
    bad = ("0" * len(good)) if good[0] != "0" else ("1" * len(good))

    res = client.get(f"{path}?e={expires}&s={bad}")
    assert res.status_code == 403
    assert res.json()["code"] == "ASSET_URL_INVALID"


def test_signature_for_another_path_does_not_work(client):
    """다른 파일의 서명을 옮겨 붙일 수 없어야 한다."""
    expires = int(time.time()) + 3600
    other = asset_urls.sign(f"/static/cases/{CASE_ID}/thumb.png", expires)

    res = client.get(f"/static/cases/{CASE_ID}/slices/slice_035.png?e={expires}&s={other}")
    assert res.status_code == 403


def test_expired_signature_says_so(client):
    """만료는 새로 고치면 되는 상황이라 사유를 구분해 알려준다."""
    expires = int(time.time()) - 10
    path = f"/static/cases/{CASE_ID}/thumb.png"
    res = client.get(f"{path}?e={expires}&s={asset_urls.sign(path, expires)}")

    assert res.status_code == 403
    assert res.json()["code"] == "ASSET_URL_EXPIRED"
    assert "새로 고쳐" in res.json()["message"]


def test_non_case_static_paths_are_untouched(client):
    """mock 이미지·데모 결과는 실제 의료영상이 아니라 검사하지 않는다."""
    res = client.get("/static/images/does-not-exist.png")
    assert res.status_code == 404  # 403 이 아니다 (서명 검사를 하지 않았다는 뜻)


# ------------------------------------------------- API 가 주는 URL 은 동작하는가
# 테스트 픽스처의 케이스는 합성 mock 이라 자산이 `/static/images/` 아래에 있다
# (실제 의료영상이 아니라 보호 대상이 아니다). 실제 등록된 케이스는
# `/static/cases/<case_id>/...` 를 쓰므로, 그 경로가 서명되는지를 확인한다.
REAL_ASSET_PATH = f"/static/cases/{CASE_ID}/slices/slice_035.png"


def test_absolute_url_signs_real_case_assets():
    """URL 을 만드는 곳이 한 군데라 여기만 확인하면 모든 응답이 함께 보호된다."""
    from app.static_files import absolute_url

    signed = absolute_url(REAL_ASSET_PATH)
    path, query = _path_and_query(signed)
    assert path == REAL_ASSET_PATH
    assert "s" in query and "e" in query


def test_absolute_url_does_not_sign_mock_assets():
    """합성 자리표시자까지 서명하면 개발이 불편해질 뿐 얻는 것이 없다."""
    from app.static_files import absolute_url

    _, query = _path_and_query(absolute_url("/static/images/202_t1.png"))
    assert query == {}


def test_signed_url_from_absolute_url_actually_works(client):
    """만든 서명이 미들웨어를 실제로 통과하는가 (규칙이 갈리면 화면이 깨진다)."""
    from app.static_files import absolute_url

    parsed = urlparse(absolute_url(REAL_ASSET_PATH))
    res = client.get(f"{parsed.path}?{parsed.query}")
    # 파일이 실제로 있으면 200, 없으면 404 — **403 이면 서명 규칙이 어긋난 것이다**
    assert res.status_code != 403, "생성한 서명이 검증을 통과하지 못했다"


def test_mock_case_response_is_not_broken_by_signing(user_a):
    """합성 케이스도 그대로 동작해야 한다 (서명 도입이 기존 흐름을 깨지 않는다)."""
    body = user_a.get(f"/api/cases/{CASE_ID}").json()
    assert body["image_url"]
    assert body["gradable"] is True


# ------------------------------------------------------------------ 서명 규칙
def test_signature_depends_on_path_and_expiry():
    expires = 1_800_000_000
    a = asset_urls.sign("/static/cases/A/x.png", expires)
    b = asset_urls.sign("/static/cases/B/x.png", expires)
    c = asset_urls.sign("/static/cases/A/x.png", expires + 1)
    assert len({a, b, c}) == 3


def test_add_signature_leaves_other_urls_alone():
    plain = "http://host/static/images/mock.png"
    assert asset_urls.add_signature(plain) == plain


def test_add_signature_is_not_applied_twice():
    once = asset_urls.add_signature("http://host/static/cases/A/x.png")
    assert asset_urls.add_signature(once) == once
    assert once.count("s=") == 1


def test_add_signature_handles_relative_paths():
    signed = asset_urls.add_signature("/static/cases/A/x.png")
    path, query = _path_and_query(signed)
    assert path == "/static/cases/A/x.png"
    assert "s" in query


# ------------------------------------------------------------------ 유효기간
def test_default_ttl_outlives_a_learning_session(monkeypatch):
    """케이스를 열어두고 한참 뒤에 slice 를 넘겨도 끊기지 않아야 한다."""
    monkeypatch.delenv(asset_urls.TTL_ENV, raising=False)
    assert asset_urls.ttl_seconds() >= 60 * 60


def test_ttl_is_clamped_to_something_sane(monkeypatch):
    """너무 짧으면 학습 도중 끊기고, 너무 길면 사실상 공개다."""
    monkeypatch.setenv(asset_urls.TTL_ENV, "1")
    assert asset_urls.ttl_seconds() >= 60

    monkeypatch.setenv(asset_urls.TTL_ENV, "99999999999")
    assert asset_urls.ttl_seconds() <= 60 * 60 * 24 * 30


def test_invalid_ttl_falls_back_without_crashing(monkeypatch):
    monkeypatch.setenv(asset_urls.TTL_ENV, "하루")
    assert asset_urls.ttl_seconds() == asset_urls.DEFAULT_TTL_SECONDS


def test_health_reports_asset_protection(client):
    state = client.get("/health").json()["asset_urls"]
    assert state["protected_prefix"] == "/static/cases/"
    assert state["ttl_seconds"] > 0
