"""
백업 검증 (자율 루프 #25).

**"파일이 생겼다"와 "그 파일에 데이터가 들어 있다"는 다르다.**
이 프로젝트에서 잃으면 다시 만들 수 없는 것은 학습 이력이다(케이스는 파이프라인으로
다시 만들 수 있다). 백업이 조용히 실패하는 방식은 셋이다:

  - DATABASE_URL 을 주지 않고 돌려 **엉뚱한(비어 있는) 개발 DB** 를 백업한다
  - 디스크가 차서 잘린 파일이 남는다 (크기만 보면 그럴듯하다)
  - pg_dump 가 일부만 덤프하고 끝난다

셋 다 "백업 완료" 가 찍히고 사고가 나야 알게 된다. 그래서 만든 뒤 열어서 확인한다.
"""
import sqlite3

import pytest

from scripts import backup_db

TABLES = backup_db.IRREPLACEABLE_TABLES


def _make_db(path, users=0, consents=0):
    conn = sqlite3.connect(path)
    for table in TABLES:
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    for _ in range(users):
        conn.execute("INSERT INTO users DEFAULT VALUES")
    for _ in range(consents):
        conn.execute("INSERT INTO consents DEFAULT VALUES")
    conn.commit()
    conn.close()
    return path


# ------------------------------------------------------------ SQLite 검증
def test_counts_rows_in_the_backup_file(tmp_path):
    db = _make_db(tmp_path / "b.sqlite", users=3, consents=5)
    counts = backup_db.verify_sqlite(db)
    assert counts["users"] == 3
    assert counts["consents"] == 5
    assert counts["submissions"] == 0


def test_truncated_backup_is_detected(tmp_path):
    # 디스크가 차서 절반만 쓰인 상황. 크기만 보면 그럴듯하다.
    db = _make_db(tmp_path / "b.sqlite", users=200)
    data = db.read_bytes()
    db.write_bytes(data[: len(data) // 2])

    with pytest.raises(Exception) as exc:
        backup_db.verify_sqlite(db)
    assert "malformed" in str(exc.value) or "손상" in str(exc.value)


def test_missing_table_is_reported_not_crashed(tmp_path):
    # 구버전 스키마로 뜬 DB 를 백업한 경우. 죽지 않고 -1 로 알린다.
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    counts = backup_db.verify_sqlite(path)
    assert counts["users"] == 0
    assert counts["learning_events"] == -1


# ------------------------------------------------------ PostgreSQL 덤프 검증
def _dump(tmp_path, body):
    path = tmp_path / "d.sql"
    path.write_text(body, encoding="utf-8")
    return path


def test_parses_copy_blocks_from_a_plain_dump(tmp_path):
    dump = _dump(
        tmp_path,
        "SET statement_timeout = 0;\n"
        "COPY public.users (user_id, email) FROM stdin;\n"
        "u_1\ta@x.com\n"
        "u_2\tb@x.com\n"
        "\.\n"
        "\n"
        "COPY public.consents (id, key) FROM stdin;\n"
        "1\tagree_terms\n"
        "\.\n",
    )
    counts = backup_db.verify_postgres_dump(dump)
    assert counts["users"] == 2
    assert counts["consents"] == 1
    # 덤프에 아예 없는 테이블은 0 이 아니라 -1 (구분해야 한다)
    assert counts["learning_events"] == -1


def test_unterminated_dump_is_detected(tmp_path):
    # pg_dump 가 도중에 끊긴 경우. 마지막 COPY 블록이 닫히지 않는다.
    dump = _dump(
        tmp_path,
        "COPY public.users (user_id) FROM stdin;\nu_1\nu_2\n",
    )
    with pytest.raises(RuntimeError) as exc:
        backup_db.verify_postgres_dump(dump)
    assert "users" in str(exc.value)


def test_empty_dump_reports_nothing_found(tmp_path):
    counts = backup_db.verify_postgres_dump(_dump(tmp_path, "-- 아무것도 없음\n"))
    assert all(v == -1 for v in counts.values())


# ---------------------------------------------------------------- 대조 판정
def test_matching_counts_pass():
    counts = {"users": 3, "consents": 3, "submissions": 1, "learning_events": 7}
    assert backup_db.report_verification(counts, dict(counts)) is True


def test_backup_missing_rows_that_source_has_fails():
    source = {"users": 3, "consents": 3, "submissions": 0, "learning_events": 0}
    backup = {"users": 0, "consents": 0, "submissions": 0, "learning_events": 0}
    assert backup_db.report_verification(source, backup) is False


def test_backup_with_fewer_rows_still_passes():
    # 스냅샷 이후에 새 행이 들어올 수 있다. 이건 정상이다.
    source = {"users": 5, "consents": 5, "submissions": 2, "learning_events": 9}
    backup = {"users": 4, "consents": 4, "submissions": 2, "learning_events": 9}
    assert backup_db.report_verification(source, backup) is True


def test_backup_with_more_rows_than_source_fails():
    # 다른 DB 를 백업했다는 신호다.
    source = {"users": 1, "consents": 1, "submissions": 0, "learning_events": 0}
    backup = {"users": 90, "consents": 90, "submissions": 0, "learning_events": 0}
    assert backup_db.report_verification(source, backup) is False


def test_table_missing_from_backup_fails():
    source = {"users": 3, "consents": 3, "submissions": 0, "learning_events": 0}
    backup = {"users": 3, "consents": 3, "submissions": 0, "learning_events": -1}
    assert backup_db.report_verification(source, backup) is False


def test_empty_source_is_flagged_separately():
    # 백업 자체는 성공이다(원본을 그대로 옮겼다). 하지만 운영 DB 를 백업하려던
    # 것이었다면 DATABASE_URL 이 엉뚱한 곳을 보고 있다는 신호다.
    empty = {t: 0 for t in TABLES}
    assert backup_db.source_is_empty(empty) is True
    assert backup_db.report_verification(empty, dict(empty)) is True

    assert backup_db.source_is_empty({**empty, "users": 1}) is False
