"""
의존성·자산 라이선스 목록.

**이 도구는 라이선스를 판단하지 않는다.** 무엇을 쓰고 있는지를 모으고,
확인이 필요한 것을 표시할 뿐이다. "써도 되는가"는 사람이 판단할 문제다.

이 테스트가 지키는 것:
  - 의료 데이터셋·모델 가중치가 **자동으로 "문제 없음"이 되지 않는다** (BLOCKER-1)
  - 라이선스를 확인하지 못한 것을 "확인됨"으로 뭉개지 않는다
  - 수집기가 실제로 무언가를 수집한다 (빈 목록으로 "이상 없음"이 되면 안 된다)
"""
import json

import pytest

from scripts import license_inventory as inv


# ------------------------------------------------------------------ 수집
def test_collects_backend_packages():
    """빈 목록으로 '이상 없음'이 되면 안 된다."""
    rows = inv.python_packages()
    names = {r["name"] for r in rows}
    assert len(rows) >= 8, f"백엔드 패키지를 제대로 수집하지 못했다: {names}"
    for known in ("fastapi", "sqlalchemy", "numpy", "pillow"):
        assert known in names


def test_backend_packages_report_versions_and_licenses():
    rows = {r["name"]: r for r in inv.python_packages()}
    fastapi = rows["fastapi"]
    assert fastapi["version"] != inv.UNKNOWN
    assert "MIT" in fastapi["license"]


def test_collects_frontend_packages():
    rows = inv.node_packages()
    names = {r["name"] for r in rows}
    assert "vue" in names
    assert "vitest" in names


# ------------------------------------------------------ 확인 필요 판정
def test_lgpl_is_flagged_for_review():
    """금지가 아니라 **확인 필요**다 — 배포 형태에 따라 의무가 달라진다."""
    reason = inv.needs_attention({"name": "x", "license": "LGPL with exceptions"})
    assert reason is not None
    assert "의무가 생길 수 있다" in reason


@pytest.mark.parametrize("license_text", ["GPL-3.0", "AGPL-3.0", "SSPL-1.0", "Proprietary"])
def test_copyleft_and_proprietary_are_flagged(license_text):
    assert inv.needs_attention({"name": "x", "license": license_text}) is not None


@pytest.mark.parametrize("license_text", ["MIT", "BSD-3-Clause", "Apache-2.0", "ISC"])
def test_permissive_licenses_are_not_flagged(license_text):
    """아무거나 표시하면 목록이 쓸모없어진다."""
    assert inv.needs_attention({"name": "x", "license": license_text}) is None


def test_unknown_license_is_flagged_not_assumed_fine():
    """**확인하지 못한 것을 '문제 없음'으로 뭉개지 않는다.**"""
    reason = inv.needs_attention({"name": "x", "license": inv.UNKNOWN})
    assert reason is not None
    assert "확인하지 못했다" in reason


# ------------------------------------------- 코드가 아닌 자산 (핵심)
def test_medical_dataset_and_weights_are_never_auto_resolved():
    """**의료 데이터셋과 모델 가중치는 자동으로 '문제 없음'이 될 수 없다.**

    코드 라이선스와 전혀 다른 문제이고, BLOCKER-1 로 열려 있다.
    """
    assets = {a["name"]: a for a in inv.NON_CODE_ASSETS}
    dataset = next(a for n, a in assets.items() if "VS-SEG" in n)
    weights = next(a for n, a in assets.items() if "가중치" in n)

    for asset in (dataset, weights):
        assert asset["status"] == "NEEDS_LICENSE_REVIEW"
        assert asset["blocker"] == "BLOCKER-1"
        assert asset["in_repo"] is False


def test_inventory_lists_unresolved_blockers():
    result = inv.build_inventory()
    assert "BLOCKER-1" in result["unresolved_blockers"]


def test_inventory_states_it_does_not_judge():
    result = inv.build_inventory()
    assert "판단하지 않습니다" in result["note"]


# ------------------------------------------------------------------ 출력
def test_markdown_puts_non_code_assets_first():
    """가장 먼저 볼 것이 데이터셋·가중치다 — 목록 아래에 묻히면 안 된다."""
    text = inv.to_markdown(inv.build_inventory())
    assets_at = text.index("코드가 아닌 자산")
    backend_at = text.index("백엔드 (Python)")
    assert assets_at < backend_at


def test_markdown_marks_blockers_visibly():
    text = inv.to_markdown(inv.build_inventory())
    assert "NEEDS_LICENSE_REVIEW" in text
    assert "BLOCKER-1" in text


def test_json_output_is_serialisable(tmp_path):
    result = inv.build_inventory()
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["counts"]["python"] >= 8


def test_attention_items_do_not_fail_the_run(monkeypatch, tmp_path, capsys):
    """확인이 필요하다고 실패로 처리하지 않는다 — 판단은 사람 몫이다."""
    monkeypatch.setattr("sys.argv", ["license_inventory"])
    assert inv.main() == 0
    out = capsys.readouterr().out
    assert "판단하지 않습니다" in out
