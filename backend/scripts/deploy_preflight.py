"""
배포 직전 점검 — `docs/DEPLOYMENT.md` 0절 체크리스트 중 **기계로 확인 가능한 것**.

**사람 판단을 대신하지 않는다.** 데이터셋 이용 조건(BLOCKER-1)이나 전문가 검수 완료
여부처럼 사람이 판단할 항목은 확인하지 않고, "확인 못 함"으로 표시해 목록에 남긴다.
확인하지 못한 것을 "이상 없음"으로 뭉개면 체크리스트가 있으나 마나다.

여기서 확인하는 것
-----------------
  환경 설정      production 필수값 · 개발 전용 스위치 · rate limit · 채점 임계값
  DB            연결 · 마이그레이션 최신 여부 · 드라이버
  콘텐츠        활성 케이스 수 · gradable 여부 · 자산 파일 실재 여부
  예측 sidecar   stale 여부 (없는 것은 문제가 아니다)
  운영          운영자 계정 존재 · 백업 존재와 최신성
  보안          시크릿이 저장소 기본값이 아닌지 · CORS 와일드카드 아닌지

사용법
------
    cd backend
    # 실제 배포 환경에서 (환경변수를 그대로 두고)
    MEDISCAN_ENV=production ... python -m scripts.deploy_preflight

    # 로컬에서 배포 설정만 흉내 내어 미리 보기
    python -m scripts.deploy_preflight --simulate-production

    python -m scripts.deploy_preflight --backup-dir /var/backups/mediscan

종료코드: 배포를 막아야 하는 문제가 하나라도 있으면 1.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import config, scoring_config  # noqa: E402

# 저장소에 공개된 개발용 서명 키. 이 값이 배포에 남아 있으면 누구나 토큰을 위조할 수 있다.
DEV_SECRET = "dev-only-insecure-secret-change-me"
BACKUP_MAX_AGE_HOURS = 48

BLOCK = "block"      # 배포를 막는다
WARN = "warn"        # 배포는 되지만 알고 있어야 한다
UNKNOWN = "unknown"  # 확인하지 못했다 (사람이 봐야 한다)
OK = "ok"


class Report:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, level: str, check: str, detail: str = "") -> None:
        self.rows.append({"level": level, "check": check, "detail": detail})

    def ok(self, check, detail=""):
        self.add(OK, check, detail)

    def warn(self, check, detail=""):
        self.add(WARN, check, detail)

    def block(self, check, detail=""):
        self.add(BLOCK, check, detail)

    def unknown(self, check, detail=""):
        self.add(UNKNOWN, check, detail)

    def count(self, level: str) -> int:
        return sum(1 for r in self.rows if r["level"] == level)


# ------------------------------------------------------------------ 환경
def check_environment(report: Report) -> None:
    try:
        env = config.env()
    except config.ConfigError as exc:
        report.block("MEDISCAN_ENV", str(exc))
        return

    if env != config.PRODUCTION:
        report.warn(
            "MEDISCAN_ENV",
            f"{env} — 배포 환경에서는 production 이어야 한다 (--simulate-production 로 미리 볼 수 있다)",
        )
    else:
        report.ok("MEDISCAN_ENV", "production")

    secret = os.getenv("MEDISCAN_SECRET_KEY", "").strip()
    if not secret:
        report.block("MEDISCAN_SECRET_KEY", "미설정 — production 에서는 기동이 실패한다")
    elif secret == DEV_SECRET:
        report.block("MEDISCAN_SECRET_KEY", "저장소에 공개된 개발용 값이다 — 토큰을 위조할 수 있다")
    elif len(secret) < 32:
        report.block("MEDISCAN_SECRET_KEY", f"너무 짧다 ({len(secret)}자, 32자 이상)")
    else:
        report.ok("MEDISCAN_SECRET_KEY", f"{len(secret)}자")

    origins = os.getenv("MEDISCAN_CORS_ORIGINS", "").strip()
    if not origins:
        report.block("MEDISCAN_CORS_ORIGINS", "미설정 — production 에서는 기동이 실패한다")
    elif "*" in origins:
        report.block("MEDISCAN_CORS_ORIGINS", "와일드카드는 쓸 수 없다")
    else:
        report.ok("MEDISCAN_CORS_ORIGINS", origins)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        report.block("DATABASE_URL", "미설정 — 컨테이너 로컬 SQLite 로 떨어지면 재배포 시 데이터가 사라진다")
    elif database_url.startswith("sqlite"):
        report.warn("DATABASE_URL", "SQLite — 동시 쓰기가 한 번에 하나다. 운영은 PostgreSQL 을 권한다")
    else:
        report.ok("DATABASE_URL", database_url.split("://", 1)[0])

    # 개발 전용 스위치
    offenders = config.describe_dev_only_flags()
    if offenders:
        report.block("개발 전용 스위치", f"켜져 있다: {', '.join(offenders)} — 기동이 실패한다")
    else:
        report.ok("개발 전용 스위치", "전부 꺼져 있다")


def check_rate_limit(report: Report) -> None:
    from app import rate_limit

    try:
        rate_limit.assert_valid()
    except config.ConfigError as exc:
        report.block("요청 수 제한", str(exc).split(".")[0])
        return
    status = rate_limit.describe_status()
    if status["mode"] == rate_limit.EXTERNAL:
        report.warn("요청 수 제한", "앱에서 하지 않는다 — 앞단 프록시·WAF 가 /api/auth/* 를 막고 있어야 한다")
    else:
        report.ok("요청 수 제한", f"mode={status['mode']}")


def check_scoring(report: Report) -> None:
    try:
        scoring_config.assert_valid()
    except config.ConfigError as exc:
        report.block("채점 임계값", str(exc))
        return
    thresholds = scoring_config.thresholds()
    default = (
        thresholds["match_dice"] == scoring_config.DEFAULT_MATCH_DICE
        and thresholds["partial_dice"] == scoring_config.DEFAULT_PARTIAL_DICE
    )
    detail = f"match={thresholds['match_dice']} partial={thresholds['partial_dice']}"
    if default:
        report.ok("채점 임계값", detail + " (기본값)")
    else:
        report.warn("채점 임계값", detail + " — 환경변수로 덮여 있다. 의도한 값인지 확인")
    # 값 자체의 교육적 타당성은 여기서 판단할 수 없다
    report.unknown("채점 임계값 교육적 타당성", "전문가 검토 대상 (RELEASE_READINESS E3 / BLOCKER-2)")


# ------------------------------------------------------------------ DB
def check_database(report: Report) -> None:
    try:
        from sqlalchemy import text

        from app.db import DATABASE_URL, engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        from app import db_connection

        described = db_connection.describe(DATABASE_URL)
        report.ok("DB 연결", f"{described['label']} ({described['host_suffix'] or 'local'})")

        # 연결 방식이 용도에 맞는지. **막지 않는다** — 인프라 사정을 우리가 알 수 없다.
        for note in db_connection.advisories(DATABASE_URL, purpose="runtime"):
            if "serverless" in note or "prepared statement" in note:
                report.warn("DB 연결 방식", note)
        if db_connection.is_transaction_pooler_url(DATABASE_URL):
            report.warn(
                "마이그레이션·백업 연결",
                "런타임이 Transaction pooler 다. **마이그레이션과 백업은 Direct connection** 으로 "
                "따로 돌리세요 (스키마 변경·pg_dump 는 세션 수준 기능을 씁니다)",
            )
    except Exception as exc:
        report.block("DB 연결", f"{type(exc).__name__}: {exc}")
        return

    try:
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from app.db import engine

        script = ScriptDirectory.from_config(_alembic_config())
        head = script.get_current_head()
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        if current == head:
            report.ok("마이그레이션", f"최신 ({head})")
        else:
            report.block("마이그레이션", f"현재 {current} / 최신 {head} — 기동 시 upgrade 되지만 확인 필요")
    except Exception as exc:
        report.unknown("마이그레이션", f"확인하지 못했다: {type(exc).__name__}")


def _alembic_config():
    """app/db.py 와 같은 방식으로 alembic 설정을 만든다 (기준이 갈리면 안 된다)."""
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


# ------------------------------------------------------------------ 콘텐츠
def check_content(report: Report) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.grading import is_gradable
    from app.models import Case
    from app.static_files import STATIC_DIR, STATIC_URL_PREFIX

    with SessionLocal() as db:
        cases = db.scalars(select(Case)).all()
        active = [c for c in cases if c.is_active]
        gradable = [c for c in active if is_gradable(c)]

        if not active:
            report.block("활성 케이스", "하나도 없다 — 학습자가 할 수 있는 것이 없다")
        else:
            report.ok("활성 케이스", f"{len(active)}건 (전체 {len(cases)}건)")

        if len(gradable) < len(active):
            report.warn(
                "채점 가능 케이스",
                f"{len(gradable)}/{len(active)} — 기준 마스크가 없는 케이스는 제출이 막힌다",
            )
        elif active:
            report.ok("채점 가능 케이스", f"{len(gradable)}/{len(active)}")

        # DB 가 가리키는 자산이 실제로 있는지
        missing = []
        for case in active:
            for url in (case.image_url, case.thumbnail_url, case.reference_mask_url):
                if not url or not url.startswith(STATIC_URL_PREFIX):
                    continue
                relative = url[len(STATIC_URL_PREFIX) :].lstrip("/")
                if not (STATIC_DIR / relative).exists():
                    missing.append(f"{case.case_id}:{Path(relative).name}")
        if missing:
            report.block(
                "케이스 자산 파일",
                f"{len(missing)}건 없음 — 학습자가 빈 화면을 본다 ({', '.join(missing[:3])}…)",
            )
        elif active:
            report.ok("케이스 자산 파일", "DB 가 가리키는 파일이 전부 있다")

        # 전문가 소견 (막지는 않는다 — 없으면 없다고 표시된다)
        without_findings = [c for c in active if c.findings_status != "approved"]
        if without_findings:
            report.warn(
                "전문가 소견",
                f"{len(without_findings)}/{len(active)} 케이스가 미검토 — 화면에 그대로 표시된다 (BLOCKER-2)",
            )


def check_sidecars(report: Report) -> None:
    from sqlalchemy import func, select

    from app import inference, sidecar_lifecycle as life
    from app.db import SessionLocal
    from app.models import Case, CaseSlice
    from app.static_files import STATIC_DIR

    stale = []
    with SessionLocal() as db:
        for case in db.scalars(select(Case).where(Case.is_active.is_(True))):
            module = inference.get_module(case.body_part)
            voxels = db.scalar(
                select(func.sum(CaseSlice.lesion_area_px)).where(CaseSlice.case_id == case.case_id)
            )
            result = life.evaluate(
                case.case_id,
                STATIC_DIR / "cases" / case.case_id,
                current_model_version=getattr(module, "MODEL_VERSION", None) if module else None,
                registered_gt_voxels=int(voxels) if voxels else None,
            )
            if result["needs_recompute"]:
                stale.append(case.case_id)

    if stale:
        report.warn(
            "예측 sidecar",
            f"오래된 예측 {len(stale)}건: {', '.join(stale)} — 채점과 무관하지만 화면에 옛 정보가 나간다",
        )
    else:
        report.ok("예측 sidecar", "오래된 예측 없음")


# ------------------------------------------------------------------ 운영
def check_backup_tooling(report: Report) -> None:
    """백업을 **뜨는 데 필요한 도구가 있는가.**

    PostgreSQL 백업은 `pg_dump` 를 부른다. 없으면 백업 명령이 실패하는데,
    그 사실을 **첫 백업을 시도하는 순간**에야 알게 된다 — 보통 배포한 뒤다.
    (이 저장소를 만든 개발 PC 가 정확히 그 상태였다.)
    """
    import shutil

    from app.db import DATABASE_URL

    if DATABASE_URL.startswith("sqlite"):
        report.ok("백업 도구", "SQLite 는 내장 온라인 백업 API 를 쓴다 (외부 도구 불필요)")
        return

    found = shutil.which("pg_dump")
    if found:
        report.ok("백업 도구", "pg_dump 사용 가능")
    else:
        report.block(
            "백업 도구",
            "pg_dump 를 찾을 수 없다 — PostgreSQL 백업을 뜰 수 없다. "
            "postgresql-client 를 설치하세요 (백업 없이 Closed Beta 를 열면 "
            "사고 한 번에 학습 이력이 전부 사라진다)",
        )


def check_operations(report: Report, backup_dir: Path | None) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()
    if not admins:
        report.block(
            "운영자 계정",
            "없다 — 콘텐츠 관리를 할 수 없다 (python -m scripts.grant_admin --email <이메일>)",
        )
    else:
        report.ok("운영자 계정", f"{len(admins)}명")

    check_backup_tooling(report)

    if backup_dir is None:
        report.unknown("백업", "--backup-dir 을 주지 않아 확인하지 못했다")
        return

    if not backup_dir.exists():
        report.block("백업", f"폴더가 없다: {backup_dir}")
        return

    backups = sorted(
        [p for p in backup_dir.glob("mediscan-*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not backups:
        report.block("백업", f"백업 파일이 하나도 없다: {backup_dir}")
        return

    latest = backups[0]
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc)
    if age > timedelta(hours=BACKUP_MAX_AGE_HOURS):
        report.warn("백업", f"가장 최근 백업이 {age.days}일 전이다 ({latest.name})")
    else:
        report.ok("백업", f"{latest.name} ({int(age.total_seconds() // 3600)}시간 전, 총 {len(backups)}개)")

    report.unknown(
        "백업 복구 훈련",
        f"python -m scripts.restore_drill --backup {latest} 로 확인하세요",
    )


# ------------------------------------------------- 사람이 판단할 항목
def check_social_login(report: Report) -> None:
    """검증 없는 SNS 로그인이 열려 있지 않은지.

    검증이 없으면 토큰 값만 아는 사람이 그 계정으로 들어간다. production 에서는
    앱이 거부하지만, 배포 전에 **어떤 제공자가 쓸 수 있는지** 알고 있어야 한다.
    """
    from app import social_auth

    state = social_auth.describe()
    if state["verified"]:
        report.ok("SNS 실검증", f"설정됨: {', '.join(state['verified'])}")
    if state["unverified"]:
        report.warn(
            "SNS 실검증",
            f"미설정: {', '.join(state['unverified'])} — production 에서 503 으로 거부된다 "
            "(계정 탈취를 막기 위해서다). 쓰려면 각 사 앱 ID 를 설정한다",
        )


def add_human_checks(report: Report) -> None:
    report.unknown("데이터셋·모델 이용 조건", "외부 사용자에게 열어도 되는지 (BLOCKER-1)")
    report.unknown("전문가 GT 검수", "마스크가 의학적으로 옳은지 (BLOCKER-2)")
    report.unknown("개인정보·규제 검토", "동의 이력 보관·접속기록 범위 (BLOCKER-3)")
    report.unknown(
        "SNS 앱 등록",
        "각 사(카카오·구글·네이버)에 앱을 등록하고 ID 를 받아야 실검증을 켤 수 있다",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="배포 직전 점검 (사람 판단을 대신하지 않는다)")
    parser.add_argument("--backup-dir", help="백업 폴더 (있으면 최신성까지 확인한다)")
    parser.add_argument(
        "--simulate-production",
        action="store_true",
        help="로컬에서 배포 설정을 흉내 내어 미리 본다 (환경변수를 임시로 채운다)",
    )
    args = parser.parse_args()

    if args.simulate_production:
        os.environ.setdefault("MEDISCAN_ENV", "production")
        print("[--simulate-production] 실제 배포 값이 아니라 미리보기입니다.")
        print()

    report = Report()
    # 한 항목이 터졌다고 나머지 점검을 멈추지 않는다.
    # 배포 전에 알아야 할 것을 최대한 모아서 한 번에 보여주는 것이 목적이다.
    # (DB 가 안 붙으면 DB 관련 항목이 줄줄이 터지는데, 그때 환경 설정 점검 결과까지
    #  잃으면 무엇부터 고쳐야 할지 알 수 없다.)
    for label, run in (
        ("환경 설정", lambda: check_environment(report)),
        ("요청 수 제한", lambda: check_rate_limit(report)),
        ("채점 임계값", lambda: check_scoring(report)),
        ("DB", lambda: check_database(report)),
        ("콘텐츠", lambda: check_content(report)),
        ("예측 sidecar", lambda: check_sidecars(report)),
        ("SNS 로그인", lambda: check_social_login(report)),
        ("운영", lambda: check_operations(report, Path(args.backup_dir) if args.backup_dir else None)),
    ):
        try:
            run()
        except Exception as exc:  # noqa: BLE001 — 점검 도구가 죽으면 아무것도 못 본다
            report.block(f"{label} 점검", f"점검 중 오류: {type(exc).__name__}: {str(exc)[:120]}")
    add_human_checks(report)

    label = {OK: "통과", WARN: "주의", BLOCK: "차단", UNKNOWN: "확인못함"}
    for level in (BLOCK, WARN, UNKNOWN, OK):
        rows = [r for r in report.rows if r["level"] == level]
        if not rows:
            continue
        print(f"--- {label[level]} ({len(rows)}) ---")
        for r in rows:
            print(f"  {r['check']:26} {r['detail']}")
        print()

    blocked = report.count(BLOCK)
    print(
        f"차단 {blocked} / 주의 {report.count(WARN)} / "
        f"확인못함 {report.count(UNKNOWN)} / 통과 {report.count(OK)}"
    )
    print()
    if blocked:
        print("**차단 항목이 있어 배포하면 안 됩니다.**")
    else:
        print("기계로 확인할 수 있는 항목에는 차단 사유가 없습니다.")
    print("※ '확인못함' 은 사람이 봐야 하는 항목입니다. 통과가 아닙니다.")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
