"""
DB 연결 방식 판별 — 특히 Supabase 의 세 가지 연결 모드.

==========================================================================
**포트 번호만으로 판별하면 틀린다.**
==========================================================================
Supabase 는 연결 방법이 셋이고, **세션 풀러도 5432 를 쓴다.**
그래서 host 와 사용자명까지 봐야 무엇인지 알 수 있다.

| 방식 | host | port | 사용자명 | 특징 |
|---|---|---|---|---|
| Direct | `db.<ref>.supabase.co` | 5432 | `postgres` | 전용 연결. prepared statement 사용 가능. 기본은 IPv6 |
| Session pooler | `<region>.pooler.supabase.com` | 5432 | `postgres.<ref>` | 연결이 세션 동안 유지돼 **direct 처럼 동작**. IPv4 가능 |
| Transaction pooler | `<region>.pooler.supabase.com` | 6543 | `postgres.<ref>` | 트랜잭션 단위로 연결을 돌려쓴다. **prepared statement 제약** |

(풀러는 Supavisor 다. 예전 PgBouncer 기준으로 알고 있으면 세부가 다르다.)

무엇을 어디에 쓰나
-----------------
  마이그레이션(Alembic) · 백업/복구   **Direct 를 쓴다.**
      스키마 변경과 pg_dump 는 세션 수준 기능을 쓴다. 트랜잭션 풀러에서는 깨질 수 있다.
  상시 실행 백엔드                     Direct 를 기본으로 하고, 필요하면 Session pooler.
      (IPv4 만 되는 환경, 연결 수가 많은 경우 등)
  serverless / 짧은 연결               Transaction pooler.
      이 프로젝트는 상시 실행 프로세스라 해당하지 않는다.

**여기서는 판별하고 알려줄 뿐, 연결 문자열을 만들어내지 않는다.**
실제 값은 Supabase Dashboard 의 Connect 에서 받은 것을 그대로 쓴다 —
우리가 host 패턴을 조립하면 Supabase 가 형식을 바꿨을 때 조용히 틀린다.
"""
import re
from urllib.parse import unquote, urlparse

# --- 연결 모드 ---------------------------------------------------------
DIRECT = "direct"
SESSION_POOLER = "session_pooler"
TRANSACTION_POOLER = "transaction_pooler"
OTHER_POSTGRES = "postgres_other"  # Supabase 가 아닌 PostgreSQL
SQLITE = "sqlite"
UNKNOWN = "unknown"

MODE_LABEL = {
    DIRECT: "Supabase Direct connection",
    SESSION_POOLER: "Supabase Session pooler (Supavisor)",
    TRANSACTION_POOLER: "Supabase Transaction pooler (Supavisor)",
    OTHER_POSTGRES: "PostgreSQL (Supabase 아님)",
    SQLITE: "SQLite",
    UNKNOWN: "알 수 없음",
}

# host 로 Supabase 인지 판별한다. 사용자명·포트는 보조 신호다.
SUPABASE_DIRECT_HOST = re.compile(r"^db\.[a-z0-9]+\.supabase\.(co|com)$", re.I)
SUPABASE_POOLER_HOST = re.compile(r"\.pooler\.supabase\.com$", re.I)
# 세션 풀러 사용자명은 `postgres.<project_ref>` 형태다
POOLER_USER = re.compile(r"^postgres\.[a-z0-9]+$", re.I)

TRANSACTION_POOLER_PORT = 6543


def parse(url: str) -> dict:
    """연결 문자열에서 모드와 특징을 읽는다. **비밀번호는 담지 않는다.**"""
    if not url:
        return {"mode": UNKNOWN, "host": None, "port": None, "user": None}

    if url.startswith("sqlite"):
        return {"mode": SQLITE, "host": None, "port": None, "user": None, "driver": "sqlite"}

    # postgresql+psycopg2:// 같은 드라이버 접미사를 떼고 파싱한다
    normalised = re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", url, flags=re.I)
    parsed = urlparse(normalised)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    user = unquote(parsed.username or "")

    info = {
        "host": host,
        "port": port,
        "user": user,
        "database": (parsed.path or "/").lstrip("/") or None,
        "driver": url.split("://", 1)[0],
        "sslmode": _query_value(parsed.query, "sslmode"),
    }

    if SUPABASE_POOLER_HOST.search(host):
        # **포트로 세션/트랜잭션을 가른다 — 단, host 가 풀러일 때만 유효한 구분이다.**
        info["mode"] = TRANSACTION_POOLER if port == TRANSACTION_POOLER_PORT else SESSION_POOLER
        info["is_supabase"] = True
        info["pooler_user_ok"] = bool(POOLER_USER.match(user))
        return info

    if SUPABASE_DIRECT_HOST.match(host):
        info["mode"] = DIRECT
        info["is_supabase"] = True
        return info

    if normalised.startswith("postgresql"):
        info["mode"] = OTHER_POSTGRES
        info["is_supabase"] = False
        return info

    info["mode"] = UNKNOWN
    info["is_supabase"] = False
    return info


def _query_value(query: str, key: str) -> str | None:
    for part in (query or "").split("&"):
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    return None


def is_pooled(url: str) -> bool:
    return parse(url)["mode"] in (SESSION_POOLER, TRANSACTION_POOLER)


def is_transaction_pooler_url(url: str) -> bool:
    """트랜잭션 풀러인가. prepared statement 제약이 있는 유일한 모드다."""
    return parse(url)["mode"] == TRANSACTION_POOLER


def describe(url: str) -> dict:
    """/health · 배포 점검에 실을 요약. **비밀번호·전체 URL 은 넣지 않는다.**"""
    info = parse(url)
    return {
        "mode": info["mode"],
        "label": MODE_LABEL.get(info["mode"], info["mode"]),
        # host 는 프로젝트 식별자가 들어 있어 통째로 노출하지 않는다
        "host_suffix": _host_suffix(info.get("host")),
        "port": info.get("port"),
        "sslmode": info.get("sslmode"),
        "notes": advisories(url, purpose="runtime"),
    }


def _host_suffix(host: str | None) -> str | None:
    """`db.abcdefgh.supabase.co` -> `*.supabase.co`. 어느 서비스인지만 알린다."""
    if not host:
        return None
    parts = host.split(".")
    return "*." + ".".join(parts[-2:]) if len(parts) > 2 else host


# ------------------------------------------------------------- 권고 사항
def advisories(url: str, *, purpose: str) -> list[str]:
    """이 용도로 이 연결을 쓸 때 알아야 할 것.

    purpose: "migration" | "backup" | "runtime"

    **막지 않는다.** 사용자의 인프라 사정(IPv4 전용 네트워크 등)을 우리가 알 수 없다.
    알아야 할 것을 알려줄 뿐이다.
    """
    info = parse(url)
    mode = info["mode"]
    notes: list[str] = []

    if mode == SQLITE:
        if purpose == "runtime":
            notes.append("SQLite 는 쓰기가 한 번에 하나다. 운영은 PostgreSQL 을 권한다.")
        return notes

    if mode == TRANSACTION_POOLER:
        notes.append(
            "Transaction pooler 는 트랜잭션 단위로 연결을 돌려쓴다 — "
            "prepared statement 가 세션에 남지 않는다."
        )
        if purpose in ("migration", "backup"):
            notes.append(
                f"**{purpose} 에는 Direct connection 을 쓰세요.** "
                "스키마 변경과 pg_dump 는 세션 수준 기능을 씁니다."
            )
        else:
            notes.append(
                "이 서비스는 상시 실행 프로세스라 Transaction pooler 가 필요하지 않습니다 "
                "(serverless 용입니다). Direct 또는 Session pooler 를 쓰세요."
            )

    if mode == SESSION_POOLER:
        notes.append(
            "Session pooler 는 연결이 세션 동안 유지돼 Direct 처럼 동작합니다 "
            "(IPv4 만 되는 환경에서 쓸 수 있습니다)."
        )
        if info.get("pooler_user_ok") is False:
            notes.append(
                f"풀러 사용자명이 `postgres.<project_ref>` 형태가 아닙니다: {info.get('user')!r}. "
                "Dashboard 의 Connect 에서 받은 값을 그대로 쓰세요."
            )
        if purpose in ("migration", "backup"):
            notes.append(
                f"{purpose} 는 Direct connection 을 권합니다 (세션 풀러도 대체로 동작하지만, "
                "Direct 가 가장 확실합니다)."
            )

    if mode == DIRECT:
        notes.append(
            "Direct connection 입니다 — 마이그레이션·백업에 가장 적합합니다. "
            "기본이 IPv6 이므로 IPv4 전용 네트워크에서는 연결되지 않을 수 있습니다."
        )

    if info.get("is_supabase") and not info.get("sslmode"):
        notes.append(
            "연결 문자열에 `sslmode` 가 없습니다. Supabase 는 TLS 를 요구하므로 "
            "`?sslmode=require` 를 붙이는 편이 명확합니다."
        )

    return notes
