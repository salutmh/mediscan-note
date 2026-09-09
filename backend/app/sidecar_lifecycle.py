"""
AI 예측 sidecar 수명주기 — stale 판정 · 재계산 계획 · 검증 · 승격.

==========================================================================
**AI 예측은 채점 기준이 아니다.**
==========================================================================
sidecar 가 오래됐거나 없어도 학습자의 채점은 전혀 영향을 받지 않는다
(채점 기준은 전문가 GT reference mask 뿐이다). 그래서 여기서 "실패"란
**학습이 막힌다**는 뜻이 아니라 **화면에 옛 정보가 참고로 나간다**는 뜻이다.

그럼에도 관리가 필요한 이유: 모델을 바꾸거나 GT 를 다시 export 하면 sidecar 는
**소리 없이 과거 상태로 남는다.** 화면에는 여전히 "AI 예측"으로 표시되므로
학습자가 지금 모델의 결과라고 오해한다.

수명주기
-------
    model/version -> stale 판정 -> 재계산 계획 -> 검증 -> 승격(promote)

**GPU·모델 없이도 stale 판정 / 계획 / 검증 / 승격은 전부 돌아간다.**
실제 추론(`scripts/run_model_predictions.py`)만 학습 venv 가 필요하다.

절대 하지 않는 것
----------------
- **실패한 새 결과로 기존 예측을 덮어쓰지 않는다.** 검증을 통과한 것만 승격한다.
- 승격 전 기존 sidecar 를 백업한다 (되돌릴 수 있어야 한다).
- 예측 지표를 만들어내지 않는다 — 계산은 추론 스크립트 몫이고 여기서는 옮기기만 한다.
"""
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# sidecar 스키마 버전. 이보다 낮으면 형식이 달라 재계산해야 한다.
CURRENT_SIDECAR_VERSION = 2

SIDECAR_NAME = "prediction.json"
MASK_NAME = "prediction.png"

# 승격 시 남기는 백업 폴더 이름
BACKUP_DIRNAME = "_sidecar_backup"

# ------------------------------------------------------------- stale 사유
STALE_MISSING = "sidecar_missing"
STALE_UNREADABLE = "sidecar_unreadable"
STALE_SCHEMA = "schema_outdated"
STALE_MODEL_VERSION = "model_version_changed"
STALE_WEIGHTS = "weights_changed"
STALE_GT = "ground_truth_changed"
STALE_VOLUME = "source_volume_changed"
STALE_GT_VOXELS = "gt_voxel_count_mismatch"
STALE_INCONSISTENT = "internally_inconsistent"

REASON_TEXT = {
    STALE_MISSING: "sidecar 가 없다 (ai_prediction: null 로 나간다 — 틀린 것은 아니다)",
    STALE_UNREADABLE: "sidecar 를 읽을 수 없다",
    STALE_SCHEMA: "sidecar 형식이 옛 버전이다",
    STALE_MODEL_VERSION: "모델 버전이 바뀌었다",
    STALE_WEIGHTS: "가중치 파일이 바뀌었다 (sha256 불일치)",
    STALE_GT: "전문가 GT 가 바뀌었다 (sha256 불일치)",
    STALE_VOLUME: "원본 volume 이 바뀌었다 (sha256 불일치)",
    STALE_GT_VOXELS: "예측 계산 시점의 GT voxel 수가 현재와 다르다",
    STALE_INCONSISTENT: "sidecar 내용이 스스로 모순된다",
}

# 이 사유들은 "옛 결과가 화면에 나간다"는 뜻이라 재계산이 필요하다.
# STALE_MISSING 은 다르다 — 없으면 없다고 정직하게 나가므로 재계산은 선택이다.
NEEDS_RECOMPUTE = {
    STALE_UNREADABLE,
    STALE_SCHEMA,
    STALE_MODEL_VERSION,
    STALE_WEIGHTS,
    STALE_GT,
    STALE_VOLUME,
    STALE_GT_VOXELS,
    STALE_INCONSISTENT,
}


class SidecarError(RuntimeError):
    """sidecar 를 다루다 안전하지 않은 상태가 될 때."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str | None:
    """파일 해시. 없으면 None (없는 것과 다른 것은 구분해야 한다)."""
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_sidecar(case_dir: Path) -> tuple[dict | None, str | None]:
    """(내용, 오류사유). 없으면 (None, STALE_MISSING)."""
    path = case_dir / SIDECAR_NAME
    if not path.exists():
        return None, STALE_MISSING
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, STALE_UNREADABLE
    if not isinstance(data, dict):
        return None, STALE_UNREADABLE
    return data, None


def check_internal_consistency(sidecar: dict) -> list[str]:
    """sidecar 가 스스로 모순되지 않는지.

    미검출인데 마스크 URL 이 남아 있으면 화면이 있지도 않은 예측을 그리려 한다.
    """
    problems = []
    if sidecar.get("detected") is False and sidecar.get("mask_url"):
        problems.append("미검출(detected=false)인데 mask_url 이 남아 있다")
    dice = sidecar.get("dice_vs_reference")
    if dice is not None and not (0.0 <= float(dice) <= 1.0):
        problems.append(f"dice_vs_reference 가 범위 밖이다: {dice}")
    if sidecar.get("detected") is True and not sidecar.get("mask_url"):
        problems.append("검출(detected=true)인데 mask_url 이 없다")
    return problems


def evaluate(
    case_id: str,
    case_dir: Path,
    *,
    current_model_version: str | None = None,
    weights_path: Path | None = None,
    export_dir: Path | None = None,
    registered_gt_voxels: int | None = None,
) -> dict:
    """이 케이스의 sidecar 상태를 판정한다. **파일을 고치지 않는다.**

    비교 대상이 없으면(가중치 파일이 없다, export 가 없다) 그 항목은 **건너뛴다** —
    확인하지 못한 것을 "이상 없음"으로 적지 않기 위해 `unchecked` 에 남긴다.
    """
    sidecar, read_error = read_sidecar(case_dir)
    reasons: list[str] = []
    unchecked: list[str] = []
    details: dict = {}

    if read_error:
        return {
            "case_id": case_id,
            "present": read_error != STALE_MISSING,
            "reasons": [read_error],
            "unchecked": ["model_version", "weights", "ground_truth", "source_volume"],
            "needs_recompute": read_error in NEEDS_RECOMPUTE,
            "details": {},
            "model_version": None,
        }

    details["model_version"] = sidecar.get("model_version")
    details["generated_at"] = sidecar.get("generated_at")

    # --- 스키마 버전 -------------------------------------------------------
    version = sidecar.get("sidecar_version")
    if version is None or int(version) < CURRENT_SIDECAR_VERSION:
        reasons.append(STALE_SCHEMA)

    # --- 모델 버전 ---------------------------------------------------------
    if current_model_version is None:
        unchecked.append("model_version")
    elif sidecar.get("model_version") != current_model_version:
        reasons.append(STALE_MODEL_VERSION)
        details["expected_model_version"] = current_model_version

    # --- 가중치 -----------------------------------------------------------
    recorded_weights = (sidecar.get("weights") or {}).get("sha256")
    if weights_path is None or not Path(weights_path).exists():
        unchecked.append("weights")
    elif recorded_weights is None:
        reasons.append(STALE_SCHEMA)
    else:
        actual = sha256_of(Path(weights_path))
        if actual != recorded_weights:
            reasons.append(STALE_WEIGHTS)
            details["weights_sha256"] = {"sidecar": recorded_weights, "actual": actual}

    # --- 원본 GT / volume ---------------------------------------------------
    if export_dir is None or not Path(export_dir).exists():
        unchecked.extend(["ground_truth", "source_volume"])
    else:
        export_dir = Path(export_dir)
        for key, filename, reason in (
            ("source_gt", "ground_truth_mask.npy", STALE_GT),
            ("source_volume", "t1_volume.npy", STALE_VOLUME),
        ):
            recorded = (sidecar.get(key) or {}).get("sha256")
            path = export_dir / filename
            if recorded is None:
                reasons.append(STALE_SCHEMA)
                continue
            if not path.exists():
                unchecked.append(key)
                continue
            actual = sha256_of(path)
            if actual != recorded:
                reasons.append(reason)
                details[f"{key}_sha256"] = {"sidecar": recorded, "actual": actual}

    # --- 등록된 GT voxel 수 --------------------------------------------------
    recorded_voxels = sidecar.get("reference_voxels")
    if registered_gt_voxels is None:
        unchecked.append("gt_voxels")
    elif recorded_voxels is not None and recorded_voxels != registered_gt_voxels:
        reasons.append(STALE_GT_VOXELS)
        details["gt_voxels"] = {"sidecar": recorded_voxels, "registered": registered_gt_voxels}

    # --- 자기모순 -----------------------------------------------------------
    inconsistencies = check_internal_consistency(sidecar)
    if inconsistencies:
        reasons.append(STALE_INCONSISTENT)
        details["inconsistencies"] = inconsistencies

    deduped = list(dict.fromkeys(reasons))
    return {
        "case_id": case_id,
        "present": True,
        "reasons": deduped,
        "unchecked": list(dict.fromkeys(unchecked)),
        "needs_recompute": any(r in NEEDS_RECOMPUTE for r in deduped),
        "details": details,
        "model_version": sidecar.get("model_version"),
    }


def build_plan(evaluations: list[dict], *, export_root: Path | None = None) -> dict:
    """재계산 계획. **여기서 추론을 돌리지 않는다** — 무엇을 왜 다시 계산해야 하는지 적는다."""
    recompute = [e for e in evaluations if e["needs_recompute"]]
    missing = [e for e in evaluations if STALE_MISSING in e["reasons"]]
    fine = [e for e in evaluations if not e["needs_recompute"] and STALE_MISSING not in e["reasons"]]

    # **sidecar 가 아예 없는 케이스도 계산 대상이다.**
    # 예전에는 stale 만 명령에 넣어서, 6케이스 모두 sidecar 가 없는 상태에서
    # "재계산할 케이스가 없다"고 안내했다 — 운영자는 할 일이 없다고 읽지만
    # 실제로는 **어떤 케이스에도 AI 예측이 없는** 상태였다.
    # 둘은 성격이 다르므로(오래됨 vs 처음부터 없음) 명령에서는 합치되 문구로 구분한다.
    stale_ids = [e["case_id"] for e in recompute]
    missing_ids = [e["case_id"] for e in missing]
    case_ids = stale_ids + [cid for cid in missing_ids if cid not in stale_ids]

    command = None
    if case_ids:
        root = export_root or Path("data/vs_seg_export")
        command = (
            "python -m scripts.run_model_predictions "
            f"--export-root {root} --cases {' '.join(case_ids)} "
            "--out <스테이징폴더>"
        )

    return {
        "generated_at": _now(),
        "note": (
            "AI 예측은 채점 기준이 아닙니다. sidecar 가 오래돼도 학습자의 채점은 영향을 받지 않고, "
            "화면에 옛 참고 정보가 나가는 것이 문제입니다."
        ),
        "counts": {
            "total": len(evaluations),
            "needs_recompute": len(recompute),
            "missing": len(missing),
            "up_to_date": len(fine),
        },
        "recompute": [
            {
                "case_id": e["case_id"],
                "reasons": e["reasons"],
                "reason_text": [REASON_TEXT.get(r, r) for r in e["reasons"]],
                "details": e["details"],
            }
            for e in recompute
        ],
        "missing": [e["case_id"] for e in missing],
        "up_to_date": [e["case_id"] for e in fine],
        # 확인하지 못한 항목을 "이상 없음"으로 뭉개지 않는다
        "unchecked": {
            e["case_id"]: e["unchecked"] for e in evaluations if e["unchecked"]
        },
        "steps": [
            "1) 학습 venv 에서 추론을 돌려 **스테이징 폴더**에 결과를 만든다",
            f"   {command}" if command else "   (계산할 케이스가 없다 — 전부 최신이다)",
            "2) python -m scripts.sidecar_manage validate --staging <스테이징폴더>",
            "3) 검증을 통과한 것만: python -m scripts.sidecar_manage promote --staging <스테이징폴더>",
        ],
        "safety": (
            "검증을 통과하지 못한 결과는 승격되지 않습니다. "
            "승격 시 기존 sidecar 를 백업하므로 되돌릴 수 있습니다."
        ),
    }


# ------------------------------------------------------------------ 검증
def validate_staged(
    case_id: str,
    staging_dir: Path,
    *,
    current_model_version: str | None = None,
    existing_dir: Path | None = None,
) -> dict:
    """승격 후보를 검증한다. **여기를 통과하지 못하면 덮어쓰지 않는다.**

    기존 예측을 실패한 새 결과로 갈아끼우는 것이 가장 나쁘다 — 되돌릴 근거도 사라진다.
    """
    problems: list[str] = []
    warnings: list[str] = []

    sidecar, read_error = read_sidecar(staging_dir)
    if read_error:
        return {
            "case_id": case_id,
            "ok": False,
            "problems": [REASON_TEXT.get(read_error, read_error)],
            "warnings": [],
        }

    # 필수 필드
    for field in ("case_id", "model_version", "detected", "sidecar_version", "generated_at"):
        if sidecar.get(field) is None:
            problems.append(f"필수 항목 없음: {field}")

    if sidecar.get("case_id") not in (None, case_id):
        problems.append(f"case_id 가 다르다: {sidecar.get('case_id')} != {case_id}")

    if sidecar.get("sidecar_version") is not None:
        if int(sidecar["sidecar_version"]) < CURRENT_SIDECAR_VERSION:
            problems.append(
                f"sidecar_version 이 낮다: {sidecar['sidecar_version']} < {CURRENT_SIDECAR_VERSION}"
            )

    if current_model_version and sidecar.get("model_version") != current_model_version:
        problems.append(
            f"model_version 이 현재 모델과 다르다: "
            f"{sidecar.get('model_version')} != {current_model_version}"
        )

    problems.extend(check_internal_consistency(sidecar))

    # 검출됐다면 마스크 파일이 실제로 있어야 한다
    if sidecar.get("detected") is True and not (staging_dir / MASK_NAME).exists():
        problems.append(f"검출인데 {MASK_NAME} 파일이 없다")
    if sidecar.get("detected") is False and (staging_dir / MASK_NAME).exists():
        warnings.append(f"미검출인데 {MASK_NAME} 파일이 있다 (승격 시 함께 옮기지 않는다)")

    # 기존과 비교 — 크게 나빠졌으면 사람이 보게 한다 (막지는 않는다)
    if existing_dir is not None:
        old, old_error = read_sidecar(Path(existing_dir))
        if old and not old_error:
            old_dice = old.get("dice_vs_reference")
            new_dice = sidecar.get("dice_vs_reference")
            if old_dice is not None and new_dice is not None:
                delta = float(new_dice) - float(old_dice)
                if delta < -0.10:
                    warnings.append(
                        f"기존보다 Dice 가 크게 떨어졌다: {old_dice} -> {new_dice} ({delta:+.3f}). "
                        "모델이 나빠진 것인지 확인하세요"
                    )
            if old.get("detected") is True and sidecar.get("detected") is False:
                warnings.append("기존에는 검출했는데 이번에는 미검출이다")

    return {"case_id": case_id, "ok": not problems, "problems": problems, "warnings": warnings}


# ------------------------------------------------------------------ 승격
def promote(case_id: str, staging_dir: Path, target_dir: Path, *, backup_root: Path) -> dict:
    """검증을 통과한 sidecar 를 제자리로 옮긴다.

    **호출 전에 반드시 validate_staged 를 통과시켜야 한다.** 이 함수는 검증하지 않는다.

    기존 파일은 백업으로 옮긴 뒤 교체한다. 임시 파일에 쓰고 os.replace 로 바꿔
    도중에 끊겨도 반쪽 파일이 남지 않게 한다.
    """
    staging_dir = Path(staging_dir)
    target_dir = Path(target_dir)
    sidecar_src = staging_dir / SIDECAR_NAME
    if not sidecar_src.exists():
        raise SidecarError(f"승격할 sidecar 가 없습니다: {sidecar_src}")

    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(backup_root) / f"{case_id}-{stamp}"

    backed_up = []
    for name in (SIDECAR_NAME, MASK_NAME):
        existing = target_dir / name
        if existing.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(existing, backup_dir / name)
            backed_up.append(name)

    moved = []
    for name in (SIDECAR_NAME, MASK_NAME):
        src = staging_dir / name
        if not src.exists():
            continue
        fd, tmp_name = tempfile.mkstemp(dir=str(target_dir), prefix=f".{name}.", suffix=".tmp")
        os.close(fd)
        try:
            shutil.copy2(src, tmp_name)
            os.replace(tmp_name, target_dir / name)
            moved.append(name)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # 미검출인데 옛 마스크가 남아 있으면 화면이 있지도 않은 예측을 그린다
    staged, _ = read_sidecar(staging_dir)
    if staged and staged.get("detected") is False:
        stale_mask = target_dir / MASK_NAME
        if stale_mask.exists() and MASK_NAME not in moved:
            stale_mask.unlink()
            moved.append(f"{MASK_NAME} (미검출이라 삭제)")

    return {
        "case_id": case_id,
        "promoted": moved,
        "backup": str(backup_dir) if backed_up else None,
        "backed_up": backed_up,
    }
