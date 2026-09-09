"""
동시 요청 스모크 테스트 — "여러 명이 동시에 쓰면 깨지는가".

**부하 테스트가 아니다.** 초당 몇 건을 견디는지 재는 것이 아니라, Closed Beta 규모
(수십 명)에서 **동시에 쓰기가 몰릴 때 오류가 나는지**를 본다. 알고 싶은 것은 처리량이
아니라 "500 이 나오는가" 하나다.

**왜 필요한가**
SQLite 는 쓰기가 한 번에 하나다. 두 요청이 동시에 제출하면 뒤에 온 쪽이
`database is locked` 로 실패할 수 있고, 그건 사용자에게 서버 오류로 보인다.
학습자가 같은 시간대에 몰리는 것은 수업·실습 상황에서 정상이다.

PostgreSQL 로 옮기면 사라지는 문제지만, 개발·소규모 배포에서 SQLite 를 쓸 수 있으므로
**어느 쪽에서 어떻게 깨지는지 알고 있어야 한다.**

**주소는 127.0.0.1 을 쓴다 (localhost 가 아니라)**
Windows 에서 파이썬 urllib 이 `localhost` 를 풀 때 IPv6(::1) 를 먼저 시도했다가
되돌아오느라 요청마다 **약 2초**가 더 붙는다. 이 도구를 처음 만들었을 때 그것도 모르고
"제출에 2초가 걸린다"는 결론을 낼 뻔했다. 실제 값은 네트워크 경유 44ms, 앱 내부 30ms 이고
브라우저(Chrome)는 localhost 로도 7ms 다.
**측정 도구가 자기 오차를 제품 문제로 착각하게 만들면 안 된다.**

사용법
------
    # 서버를 띄운 상태에서 (rate limit 은 꺼야 한다 - 여기서는 한도가 아니라 동시성을 본다)
    cd backend
    MEDISCAN_RATE_LIMIT=0 python -m uvicorn app.main:app --port 8010

    python -m scripts.load_smoke                      # 기본: 동시 10명
    python -m scripts.load_smoke --users 30 --rounds 3

종료코드: 실패한 요청이 하나라도 있으면 1.
"""
import argparse
import base64
import io as _io
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

CONSENTS = {
    "agree_terms": True,
    "agree_privacy": True,
    "agree_sensitive_data": True,
    "agree_ai_notice": True,
    "agree_age14": True,
    "agree_marketing": False,
}


def _mask_base64(size: int = 512, cx: int = 338, cy: int = 307, r: int = 30) -> str:
    """제출용 ROI 마스크. 실제 채점 경로를 그대로 타게 하려면 진짜 마스크가 필요하다."""
    import numpy as np
    from PIL import Image

    yy, xx = np.ogrid[:size, :size]
    mask = ((xx - cx) ** 2 + (yy - cy) ** 2) <= r**2
    buf = _io.BytesIO()
    Image.fromarray((mask * 255).astype("uint8"), mode="L").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _request(url: str, *, method: str = "GET", body=None, token=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw[:200]
    except Exception as exc:  # 연결 실패·타임아웃도 실패로 센다
        return 0, f"{type(exc).__name__}: {exc}"


PASSWORD = "pw12345678"


def signup(base: str, domain: str) -> tuple[str, str] | None:
    """(토큰, 이메일). 실패하면 None.

    **도메인을 인자로 받는 이유**: 스테이징 DB 를 상대로 돌릴 때는
    `@staging.invalid` 를 써야 한다. `@example.com` 계정이 남으면
    `verify_remote_db --expect-staging` 의 순수성 검사가 실패한다 —
    그 검사는 "운영 데이터가 섞였는가"를 보는 장치라 무디게 만들면 안 된다.
    """
    email = f"load{uuid.uuid4().hex[:10]}{domain}"
    status, body = _request(
        f"{base}/api/auth/signup",
        method="POST",
        body={"email": email, "password": PASSWORD, "nickname": "부하", "consents": CONSENTS},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    return body.get("access_token"), email


def delete_account(base: str, token: str) -> bool:
    """만든 계정을 지운다. **잔여물을 남기지 않는다.**"""
    status, _ = _request(
        f"{base}/api/auth/me", method="DELETE", token=token, body={"password": PASSWORD}
    )
    return status in (200, 204)


def main() -> int:
    parser = argparse.ArgumentParser(description="동시 요청 스모크 테스트 (부하 테스트가 아니다)")
    # localhost 가 아니라 127.0.0.1 이다 — 위 docstring 참고 (Windows 에서 요청당 약 2초 차이)
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--users", type=int, default=10, help="동시 사용자 수")
    parser.add_argument("--rounds", type=int, default=2, help="각 사용자가 제출하는 횟수")
    parser.add_argument("--case", default="VS-SEG-202")
    parser.add_argument(
        "--email-domain",
        default="@example.com",
        help="만들 계정의 도메인. 스테이징 DB 상대로 돌릴 때는 @staging.invalid 를 쓴다",
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="끝나고 만든 계정을 지운다 (스테이징 권장)"
    )
    args = parser.parse_args()

    status, _ = _request(f"{args.base}/health")
    if status != 200:
        print(f"서버에 연결할 수 없습니다: {args.base} (health={status})")
        print("MEDISCAN_RATE_LIMIT=0 으로 서버를 띄웠는지 확인하세요.")
        return 1

    print(f"대상: {args.base} / 동시 {args.users}명 x {args.rounds}회")
    print("가입 중...")
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        accounts = list(pool.map(lambda _: signup(args.base, args.email_domain), range(args.users)))

    tokens = [a[0] if a else None for a in accounts]
    failed_signups = tokens.count(None)
    tokens = [t for t in tokens if t]
    if failed_signups:
        print(f"  가입 실패 {failed_signups}건 (rate limit 이 켜져 있는지 확인하세요)")
    if not tokens:
        print("가입이 전부 실패해 진행할 수 없습니다.")
        return 1
    print(f"  {len(tokens)}명 준비")

    roi = {"type": "brush_mask", "points": [[338, 307]], "mask_png_base64": _mask_base64()}
    results: list[tuple[int, float, object]] = []

    def submit(token: str):
        started = time.perf_counter()
        status, body = _request(
            f"{args.base}/api/cases/{args.case}/submit",
            method="POST",
            body={"roi": roi},
            token=token,
        )
        return status, time.perf_counter() - started, body

    print("동시 제출 중...")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(tokens)) as pool:
        for _ in range(args.rounds):
            results.extend(pool.map(submit, tokens))
    wall = time.perf_counter() - started

    ok = [r for r in results if r[0] == 200]
    bad = [r for r in results if r[0] != 200]
    durations = sorted(r[1] for r in ok)

    print()
    print(f"요청 {len(results)}건 / {wall:.1f}초")
    print(f"  성공 {len(ok)}건 / 실패 {len(bad)}건")
    if durations:
        print(
            f"  응답시간  중앙 {statistics.median(durations) * 1000:.0f}ms"
            f"  최대 {durations[-1] * 1000:.0f}ms"
        )
        if "localhost" in args.base:
            print("  ※ --base 에 localhost 를 쓰면 Windows 에서 요청당 약 2초가 더 붙는다.")
            print("    127.0.0.1 로 다시 재세요 (도구의 오차이지 서버가 느린 것이 아니다).")

    if bad:
        print()
        print("실패 내역 (상태코드별):")
        by_status: dict[int, list] = {}
        for status, _, body in bad:
            by_status.setdefault(status, []).append(body)
        for status, bodies in sorted(by_status.items()):
            label = "연결 실패" if status == 0 else f"HTTP {status}"
            print(f"  {label}: {len(bodies)}건")
            print(f"    예: {str(bodies[0])[:160]}")
        print()
        print("※ 'database is locked' 가 보이면 SQLite 의 단일 쓰기 제약이다.")
        print("  운영에서는 PostgreSQL 을 쓴다 (docs/DEPLOYMENT.md 0절).")
        _cleanup(args, tokens)
        return 1

    print()
    print("전체 성공 - 이 규모의 동시 쓰기에서 오류가 발생하지 않았습니다.")
    _cleanup(args, tokens)
    return 0


def _cleanup(args, tokens) -> None:
    if not args.cleanup:
        return
    alive = [t for t in tokens if t]
    with ThreadPoolExecutor(max_workers=max(1, len(alive))) as pool:
        removed = sum(pool.map(lambda t: delete_account(args.base, t), alive))
    print(f"정리: 계정 {removed}/{len(alive)}개 삭제")
    if removed != len(alive):
        print("  일부가 남았습니다 — verify_remote_db --expect-staging 로 확인하세요.")


if __name__ == "__main__":
    raise SystemExit(main())
