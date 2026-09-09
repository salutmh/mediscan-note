"""
복구 훈련 — 백업으로 **실제 서비스가 뜨는지**.

`backup_db.py` 의 검증은 "파일이 읽힌다"까지다. 그건 "복구된다"와 다르다:
스키마가 현재 코드보다 옛 버전이면 되돌려도 앱이 뜨지 않는다.

이 테스트는 **훈련 도구가 실제로 실패를 잡는지** 확인한다.
"전부 통과"만 나오는 검사는 검사가 아니다.

앱을 실제로 띄우는 부분은 느려서 여기서 매번 돌리지 않는다 —
파일 판정 로직만 본다. 전체 훈련은 `scripts/restore_drill.py` 로 사람이 돌린다.
"""
import sqlite3

import pytest

from scripts import restore_drill


def _make_db(path, *, tables=None, users=0):
    conn = sqlite3.connect(path)
    for table in tables if tables is not None else restore_drill.IRREPLACEABLE_TABLES:
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    for _ in range(users):
        conn.execute("INSERT INTO users DEFAULT VALUES")
    conn.commit()
    conn.close()
    return path


# ------------------------------------------------------------------ 행 수
def test_counts_irreplaceable_tables(tmp_path):
    db = _make_db(tmp_path / "b.sqlite", users=3)
    counts = restore_drill.count_rows(db)
    assert counts["users"] == 3
    assert counts["consents"] == 0


def test_missing_table_reported_as_minus_one(tmp_path):
    """없는 테이블을 0 으로 세면 '비어 있다'와 구분되지 않는다."""
    db = _make_db(tmp_path / "b.sqlite", tables=["users"], users=1)
    counts = restore_drill.count_rows(db)
    assert counts["users"] == 1
    assert counts["consents"] == -1
    assert counts["learning_events"] == -1


def test_truncated_backup_cannot_be_counted(tmp_path):
    """디스크가 차서 절반만 쓰인 파일. 크기만 보면 그럴듯하다."""
    db = _make_db(tmp_path / "b.sqlite", users=200)
    data = db.read_bytes()
    db.write_bytes(data[: len(data) // 2])

    counts = restore_drill.count_rows(db)
    # 읽히지 않으므로 전부 -1 이어야 한다 (0 으로 뭉개면 "빈 백업"으로 보인다)
    assert all(n == -1 for n in counts.values())


# ------------------------------------------------------------------ 복원
def test_restore_copies_to_isolated_location(tmp_path):
    """**운영 DB 를 건드리지 않는다** — 복사본에서만 작업한다."""
    backup = _make_db(tmp_path / "backup.sqlite", users=2)
    workdir = tmp_path / "work"
    workdir.mkdir()

    restored = restore_drill.restore_sqlite(backup, workdir)

    assert restored.parent == workdir
    assert restored != backup
    assert backup.exists(), "원본 백업이 사라지면 안 된다"
    assert restore_drill.count_rows(restored)["users"] == 2


def test_restoring_does_not_modify_the_backup(tmp_path):
    backup = _make_db(tmp_path / "backup.sqlite", users=2)
    before = backup.read_bytes()
    workdir = tmp_path / "work"
    workdir.mkdir()

    restore_drill.restore_sqlite(backup, workdir)
    assert backup.read_bytes() == before


# ------------------------------------------------------------- PostgreSQL
def test_postgres_dump_is_refused_with_guidance(tmp_path):
    """할 수 없는 것을 할 수 있는 척하지 않는다."""
    dump = tmp_path / "backup.sql"
    dump.write_text("-- dump", encoding="utf-8")

    with pytest.raises(NotImplementedError) as exc:
        restore_drill.restore_postgres_dump(dump, tmp_path)
    assert "psql" in str(exc.value)


# ------------------------------------------------------- 훈련 스크립트 진입점
def test_missing_backup_file_is_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "sys.argv", ["restore_drill", "--backup", str(tmp_path / "nope.sqlite")]
    )
    assert restore_drill.main() == 1
    assert "백업 파일이 없습니다" in capsys.readouterr().out


def test_postgres_dump_exits_with_guidance(monkeypatch, tmp_path, capsys):
    dump = tmp_path / "backup.sql"
    dump.write_text("-- dump", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["restore_drill", "--backup", str(dump)])

    assert restore_drill.main() == 1
    assert "psql" in capsys.readouterr().out
