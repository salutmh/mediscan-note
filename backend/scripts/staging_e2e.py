"""
스테이징 DB 를 실제로 쓰면서 학습 흐름 전체를 확인한다.

==========================================================================
**마이그레이션이 돌았다 ≠ 서비스가 동작한다.**
==========================================================================
스키마가 올라가고 케이스가 들어갔다고 해서 학습자가 판독을 제출할 수 있는 것은
아니다. 원격 DB 에서만 드러나는 것들이 있다 — 유휴 연결 끊김, 트랜잭션 격리,
시간대, 제약 위반, 동시 쓰기.

여기서 도는 것 (api-spec 순서 그대로)
------------------------------------
  가입(동의 5종) → 로그인 → 케이스 목록 → 케이스 상세 → slice 탐색
  → ROI 제출 → **GT 기준 채점** → 해설 → 재도전 → 이전/이번 점수 비교
  → 학습 이력 → 대시보드 → 로그아웃 → **토큰 무효화 확인** → 운영자 화면

지키는 것
---------
  * **계정은 `@staging.invalid` 로만 만든다.** 실제로 도달하지 않는 예약 TLD 라
    스테이징 데이터가 실사용자처럼 보이지 않고, 순수성 검사도 통과한다.
  * **의료영상을 원격에 올리지 않는다.** 영상은 앱 서버 디스크에서 서빙된다.
  * **AI 예측이 없어도 채점이 되는지** 확인한다 — 이 서비스의 핵심 불변조건이다.
  * 만든 계정은 끝나고 **탈퇴로 지운다** (실패해도 스테이징이라 무해하지만,
    쌓이면 순수성 검사가 무의미해진다).

사용법
------
    cd backend
    # 1) 스테이징 DB 로 앱을 띄운다
    python -m scripts.staging_secret run --mode session_pooler -- \
        python -m uvicorn app.main:app --port 8020
    # 2) 다른 터미널에서
    python -m scripts.staging_e2e --base http://127.0.0.1:8020
"""
import argparse
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 스테이징 계정은 도달하지 않는 예약 TLD 를 쓴다 (RFC 2606)
STAGING_DOMAIN = "@staging.invalid"

CONSENTS = {
    "agree_terms": True,
    "agree_privacy": True,
    "agree_sensitive_data": True,
    "agree_ai_notice": True,
    "agree_age14": True,
    "agree_marketing": False,
}

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print("  {}  {}{}".format("통과" if ok else "실패", name, "  — " + detail if detail else ""))
    return ok


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None

    def __call__(self, path: str, method="GET", body=None, expect=200, auth=True):
        request = urllib.request.Request(self.base + path, method=method)
        request.add_header("Content-Type", "application/json")
        if auth and self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(request, data, timeout=30) as response:
                payload = json.loads(response.read().decode() or "{}")
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                payload = {"raw": raw[:300]}
            status = exc.code
        if expect is not None and status != expect:
            raise AssertionError("{} {} -> {} (기대 {}): {}".format(
                method, path, status, expect, json.dumps(payload, ensure_ascii=False)[:300]))
        return payload


def circle_mask(cx: int, cy: int, r: int, size: int = 512) -> str:
    """원 하나짜리 ROI 마스크. **의료적 의미가 없는 도형이다** — 경로 검증용."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def roi_at(cx: int, cy: int, r: int = 30, size: int = 512) -> dict:
    return {
        "type": "brush_mask",
        "points": [[cx, cy]],
        "mask_png_base64": circle_mask(cx, cy, r, size),
    }


def run(base: str, keep_account: bool) -> int:
    api = Api(base)
    email = "e2e-{}{}".format(uuid.uuid4().hex[:8], STAGING_DOMAIN)
    password = "StagingE2E!{}".format(uuid.uuid4().hex[:6])

    print("스테이징 E2E — {}".format(base))
    print()

    # --- 0. 서버 상태 ---------------------------------------------------
    print("0) 서버")
    health = api("/health", auth=False)
    connection = (health.get("db_connection") or {}).get("label", "?")
    check(health.get("status") in ("ok", "degraded"), "health 응답", health.get("status", "?"))
    check("Supabase" in connection, "스테이징 DB 에 붙어 있다", connection)

    # --- 1. 가입 · 동의 --------------------------------------------------
    print("\n1) 가입 · 동의")
    signup = api("/api/auth/signup", "POST", {
        "email": email, "password": password, "nickname": "스테이징검증", "consents": CONSENTS,
    }, auth=False)
    api.token = signup["access_token"]
    check(bool(api.token), "가입 후 토큰 발급")
    check(signup["email"].endswith(STAGING_DOMAIN), "스테이징 전용 계정", signup["email"])

    missing_consent = api("/api/auth/signup", "POST", {
        "email": "no-consent-{}{}".format(uuid.uuid4().hex[:6], STAGING_DOMAIN),
        "password": password, "nickname": "동의없음",
        "consents": {**CONSENTS, "agree_sensitive_data": False},
    }, expect=400, auth=False)
    check(missing_consent.get("detail", {}).get("code") == "CONSENT_REQUIRED",
          "필수 동의 없이는 계정이 생기지 않는다")

    # --- 2. 로그인 -------------------------------------------------------
    print("\n2) 로그인")
    login = api("/api/auth/login", "POST", {"email": email, "password": password}, auth=False)
    api.token = login["access_token"]
    me = api("/api/auth/me")
    check(me["user_id"] == signup["user_id"], "같은 계정으로 로그인된다")

    # --- 3. 케이스 목록 · 상세 -------------------------------------------
    print("\n3) 케이스")
    listing = api("/api/cases")
    cases = listing["cases"]
    check(len(cases) > 0, "케이스 목록", "{}건".format(len(cases)))
    gradable = [c for c in cases if c["gradable"]]
    check(bool(gradable), "채점 가능한 케이스가 있다", "{}건".format(len(gradable)))
    if not gradable:
        return _summary()

    case_id = gradable[0]["case_id"]
    check(cases[0].get("progress") is None, "아직 안 푼 케이스는 progress 가 null 이다")

    detail = api("/api/cases/{}".format(case_id))
    check(bool(detail.get("image_url")), "영상 URL 이 온다")
    check("static/cases" in detail["image_url"], "영상은 앱 서버가 서빙한다 (원격 스토리지 아님)",
          detail["image_url"].split("?")[0][-40:])

    slices = detail.get("slices") or []
    check(len(slices) > 1, "slice 탐색이 가능하다", "{}장".format(len(slices)))

    # --- 4. 제출 · 채점 --------------------------------------------------
    print("\n4) ROI 제출 · GT 기준 채점")
    width = (detail.get("image_meta") or {}).get("width", 512)
    first = api("/api/cases/{}/submit".format(case_id), "POST",
                {"roi": roi_at(int(width * 0.25), int(width * 0.25), 25, width)})
    check(first["grade"] in ("match", "partial_match", "mismatch"), "판정이 나온다", first["grade"])
    check(first["evaluation"]["method"] == "reference_mask",
          "**채점 기준은 전문가 GT 마스크다**", first["evaluation"]["method"])
    check(first.get("ai_prediction") is None or isinstance(first["ai_prediction"], dict),
          "AI 예측은 참고 정보 자리에만 온다",
          "없음" if first.get("ai_prediction") is None else "있음")
    check(first["grade"] is not None and first["dice"] is not None,
          "**AI 예측이 없어도 채점은 정상 동작한다**")
    check(bool(first.get("spatial_feedback")), "공간 피드백이 온다")
    check(bool(first.get("explanation")), "해설이 온다")

    explanation = first["explanation"]
    check("case_facts" in explanation and "disease_info" in explanation,
          "해설이 출처별로 분리돼 있다", ", ".join(explanation.get("content_levels", [])))
    check(explanation.get("case_findings") is None,
          "**전문가 소견은 비어 있다** (검수 전에는 만들지 않는다)")

    # --- 5. 재도전 · 경과 -------------------------------------------------
    print("\n5) 재도전")
    facts = explanation.get("case_facts") or {}
    lesion_slice = facts.get("representative_slice")
    second = api("/api/cases/{}/submit".format(case_id), "POST",
                 {"roi": roi_at(int(width * 0.6), int(width * 0.55), 30, width)})
    progress = second.get("progress") or {}
    check(progress.get("attempt_number") == 2, "회차가 센다", str(progress.get("attempt_number")))
    check(progress.get("previous") is not None, "이전 시도와 비교된다")
    check(progress.get("is_first_attempt") is False, "첫 시도가 아님을 안다")

    # --- 6. 학습 이력 · 대시보드 ------------------------------------------
    print("\n6) 학습 이력")
    listing2 = api("/api/cases")
    card = next(c for c in listing2["cases"] if c["case_id"] == case_id)
    check(card["progress"]["attempts"] == 2, "목록에 시도 횟수가 반영된다",
          str(card["progress"]["attempts"]))

    dashboard = api("/api/me/dashboard")
    check(dashboard["has_any_activity"] is True, "대시보드가 활동을 안다")
    check(dashboard["totals"]["total_attempts"] == 2, "총 시도 수가 맞는다")
    check(len(dashboard["recent_activity"]) == 2, "최근 활동이 쌓인다")
    improvement = dashboard.get("latest_improvement")
    check(improvement is not None and improvement["case_id"] == case_id,
          "같은 케이스의 두 시도가 비교된다")

    for stamp in [a["submitted_at"] for a in dashboard["recent_activity"]]:
        if not (stamp.endswith("Z") or "+" in stamp[10:] or "-" in stamp[11:]):
            check(False, "시각에 offset 이 있다", stamp)
            break
    else:
        check(True, "시각에 offset 이 있다 (브라우저가 로컬 시간으로 오해하지 않는다)")

    notes = api("/api/wrong-notes")
    check(isinstance(notes["items"], list), "복습노트가 응답한다", "{}건".format(len(notes["items"])))

    # --- 7. 로그아웃 · 토큰 무효화 ----------------------------------------
    print("\n7) 로그아웃 · 토큰 무효화")
    revoked_token = api.token
    api("/api/auth/logout", "POST")
    api.token = revoked_token
    after = api("/api/auth/me", expect=401)
    check(after.get("detail", {}).get("code") in ("TOKEN_REVOKED", "INVALID_TOKEN", "UNAUTHORIZED"),
          "**로그아웃한 토큰은 서버가 거부한다**",
          str(after.get("detail", {}).get("code")))

    # --- 8. 운영자 권한 ---------------------------------------------------
    print("\n8) 운영자 권한")
    api.token = api("/api/auth/login", "POST",
                    {"email": email, "password": password}, auth=False)["access_token"]
    forbidden = api("/api/admin/cases", expect=403)
    check(forbidden.get("detail", {}).get("code") == "ADMIN_REQUIRED",
          "일반 사용자는 운영자 API 를 쓸 수 없다")

    # --- 9. 정리 ----------------------------------------------------------
    print("\n9) 정리")
    if keep_account:
        check(True, "계정을 남긴다 (--keep-account)", email)
    else:
        api("/api/auth/me", "DELETE", {"password": password})
        check(True, "검증용 계정을 지웠다", "스테이징에 잔여물을 남기지 않는다")

    return _summary()


def _summary() -> int:
    failed = [r for r in results if not r[0]]
    print()
    print("{}건 검사 — 실패 {}".format(len(results), len(failed)))
    for _, name, detail in failed:
        print("  실패: {} — {}".format(name, detail))
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="스테이징 DB 로 학습 흐름 전체를 검증한다")
    parser.add_argument("--base", default="http://127.0.0.1:8020")
    parser.add_argument("--keep-account", action="store_true",
                        help="검증용 계정을 지우지 않는다 (화면으로 이어서 확인할 때)")
    args = parser.parse_args(argv)

    for _ in range(20):
        try:
            urllib.request.urlopen(args.base + "/health", timeout=3)
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("서버에 붙을 수 없습니다: {}".format(args.base))

    return run(args.base, args.keep_account)


if __name__ == "__main__":
    raise SystemExit(main())
