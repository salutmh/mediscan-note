"""
실제 모델 추론을 **미리 계산**해 케이스 sidecar 로 저장한다.

왜 미리 계산하나
---------------
VS_Seg 모델은 3D volume 입력이고 sliding-window 추론이라 케이스당 수 분이 걸린다.
제출 요청이 이걸 기다릴 수는 없고, 백엔드 서비스에 torch/monai 를 깔 이유도 없다.
그래서 학습 venv 로 여기서 한 번 돌려 결과만 서비스에 넘긴다.

  <static>/cases/<CASE_ID>/prediction.png    대표 slice 예측 마스크 (참고 표시용)
  <static>/cases/<CASE_ID>/prediction.json   model_version / dice / voxel 수 등
  data/vs_seg_predictions/<CASE_ID>/prediction_mask.npy   전체 volume 예측 (재검증용, gitignore)

**예측은 채점에 쓰이지 않는다.** 화면 3 에 참고 정보로만 표시된다.

사용법 (학습 venv 로 실행)
------------------------
    cd backend
    "<...>/vestibular-schwannoma/.venv/Scripts/python.exe" -m scripts.run_model_predictions \
        --export-root data/vs_seg_export --cases VS-SEG-202 \
        --verify-against "C:/.../vestibular-schwannoma/outputs"

--verify-against 를 주면 노트북 산출물(prediction_mask.npy / result.txt)과 대조한다.
대조를 통과해야 전처리 재현이 맞다고 볼 수 있다 (models/brain_mri_vs/inference.py 참고).
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
for path in (BACKEND_DIR, REPO_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.static_files import STATIC_DIR  # noqa: E402
from models.brain_mri_vs import inference  # noqa: E402

CASES_DIR = STATIC_DIR / "cases"
CASES_URL_PREFIX = "/static/cases"
PREDICTION_NPY_ROOT = BACKEND_DIR / "data" / "vs_seg_predictions"

# 예측 마스크 색 (기준 마스크와 구분되게 보라 계열). 채점과 무관한 참고 표시용이다.
PREDICTION_RGBA = (168, 85, 247, 190)

DICE_TOLERANCE = 1e-4


def file_fingerprint(path: Path) -> dict | None:
    """sidecar 가 어떤 입력/가중치로 만들어졌는지 남긴다 (stale 판별용)."""
    if not path.exists():
        return None
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "sha256": digest.hexdigest(),
    }


def dice_of(a, b) -> float:
    intersection = float(np.logical_and(a, b).sum())
    denominator = float(a.sum() + b.sum())
    return (2.0 * intersection / denominator) if denominator > 0 else 1.0


def write_prediction_png(mask_2d, path: Path) -> None:
    rgba = np.zeros((*mask_2d.shape, 4), dtype=np.uint8)
    rgba[mask_2d.astype(bool)] = PREDICTION_RGBA
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path)


def verify(case_id: str, reference_dir: Path, predicted, dice: float) -> list[str]:
    """노트북 산출물과 대조. 불일치 목록을 돌려준다."""
    problems = []
    mask_file = reference_dir / "prediction_mask.npy"
    result_file = reference_dir / "result.txt"

    if mask_file.exists():
        reference = np.load(mask_file, mmap_mode="r")
        reference = np.asarray(reference).astype(bool)
        if reference.shape != predicted.shape:
            problems.append(f"예측 shape: 기존={reference.shape} / 재현={predicted.shape}")
        elif not np.array_equal(reference, predicted):
            problems.append(
                f"예측 마스크 배열 불일치 (기존 {int(reference.sum())} voxel / "
                f"재현 {int(predicted.sum())} voxel, 겹침 Dice {dice_of(reference, predicted):.6f})"
            )
    else:
        problems.append(f"[대조 건너뜀] prediction_mask.npy 없음: {mask_file}")

    if result_file.exists():
        recorded = {}
        for line in result_file.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                recorded[key.strip()] = value.strip()
        if "dice" in recorded:
            expected = float(recorded["dice"])
            if abs(expected - dice) > DICE_TOLERANCE:
                problems.append(f"Dice: 기존={expected:.6f} / 재현={dice:.6f}")
        if "pred_voxels" in recorded:
            expected_voxels = int(recorded["pred_voxels"])
            if expected_voxels != int(predicted.sum()):
                problems.append(
                    f"예측 voxel: 기존={expected_voxels} / 재현={int(predicted.sum())}"
                )
    return problems


def run_case(case_id: str, export_dir: Path, save: bool) -> dict:
    volume = np.load(export_dir / "t1_volume.npy")
    gt = np.load(export_dir / "ground_truth_mask.npy").astype(bool)
    meta = json.loads((export_dir / "export_meta.json").read_text(encoding="utf-8"))
    representative = int(meta["representative_slice"])

    result = inference.predict_volume(volume, reference_mask=gt)
    predicted = result["mask"]
    dice = float(result["dice"])

    slice_prediction = predicted[:, :, representative]
    slice_gt = gt[:, :, representative]

    info = {
        "case_id": case_id,
        "model_version": result["model_version"],
        "dice_vs_reference": round(dice, 6),
        "predicted_voxels": int(predicted.sum()),
        "reference_voxels": int(gt.sum()),
        "detected": bool(predicted.any()),
        "representative_slice": representative,
        "representative_slice_dice": round(float(dice_of(slice_prediction, slice_gt)), 6),
        "representative_slice_predicted_px": int(slice_prediction.sum()),
        "roi_size": list(result["roi_size"]),
        "preprocess": "volume z-score (학습 노트북 cell 6 그대로)",
        "note": "참고 정보 전용. 판독훈련 채점에는 사용하지 않는다.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # --- stale 판별용 메타데이터 ---
        # 모델을 바꾸거나 volume 을 다시 export 하면 이 값들이 달라진다.
        # verify_cases.py 가 model_version / reference_voxels 를 현재 상태와 대조한다.
        "sidecar_version": 2,
        "weights": file_fingerprint(inference.weights_path()),
        "source_volume": file_fingerprint(export_dir / "t1_volume.npy"),
        "source_gt": file_fingerprint(export_dir / "ground_truth_mask.npy"),
        "regenerate_with": (
            "python -m scripts.run_model_predictions --export-root data/vs_seg_export "
            f"--cases {case_id}"
        ),
    }

    if save:
        npy_dir = PREDICTION_NPY_ROOT / case_id
        npy_dir.mkdir(parents=True, exist_ok=True)
        np.save(npy_dir / "prediction_mask.npy", predicted.astype(np.uint8))

        case_dir = CASES_DIR / case_id
        if slice_prediction.any():
            write_prediction_png(slice_prediction, case_dir / "prediction.png")
            info["mask_url"] = f"{CASES_URL_PREFIX}/{case_id}/prediction.png"
        else:
            # 미검출 케이스는 마스크 파일을 만들지 않는다 (빈 PNG 를 올리면 "예측했는데 비었다"로 오해된다)
            stale = case_dir / "prediction.png"
            if stale.exists():
                stale.unlink()
            info["mask_url"] = None

        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "prediction.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    info["_predicted"] = predicted
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 모델 추론을 미리 계산해 sidecar 로 저장")
    parser.add_argument("--export-root", type=Path, default=Path("data/vs_seg_export"))
    parser.add_argument("--cases", nargs="*", help="생략 시 export-root 안의 전체")
    parser.add_argument("--verify-against", type=Path, help="노트북 outputs 루트와 대조")
    parser.add_argument("--dry-run", action="store_true", help="추론만 하고 저장하지 않는다")
    args = parser.parse_args()

    reason = inference.unavailable_reason()
    if reason is not None:
        print(f"[중단] 모델을 쓸 수 없습니다: {reason}")
        return 1

    cases = args.cases or sorted(p.name for p in args.export_root.iterdir() if p.is_dir())
    exit_code = 0

    for case_id in cases:
        export_dir = args.export_root / case_id
        print(f"=== {case_id} ===")
        if not export_dir.exists():
            print(f"  [실패] export 없음: {export_dir}")
            exit_code = 1
            continue

        try:
            info = run_case(case_id, export_dir, save=not args.dry_run)
        except Exception as exc:
            print(f"  [실패] {exc}")
            exit_code = 1
            continue

        predicted = info.pop("_predicted")
        print(f"  window={tuple(info['roi_size'])}  device 자동 선택")
        print(
            f"  Dice(volume)={info['dice_vs_reference']}  "
            f"예측 voxel={info['predicted_voxels']:,} / GT {info['reference_voxels']:,}  "
            f"검출={info['detected']}"
        )
        print(
            f"  대표 slice {info['representative_slice']}: "
            f"Dice={info['representative_slice_dice']} "
            f"예측 {info['representative_slice_predicted_px']}px"
        )

        if args.verify_against:
            reference_dir = args.verify_against / case_id
            if not reference_dir.exists():
                print(f"  [대조 건너뜀] 기존 산출물 없음: {reference_dir}")
            else:
                problems = verify(case_id, reference_dir, predicted, info["dice_vs_reference"])
                if problems:
                    exit_code = 1
                    print("  [대조 실패]")
                    for p in problems:
                        print(f"    - {p}")
                else:
                    print("  [대조 성공] 노트북 산출물과 완전히 일치")

        if not args.dry_run:
            print(f"  저장: {CASES_DIR / case_id / 'prediction.json'}")
        print()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
