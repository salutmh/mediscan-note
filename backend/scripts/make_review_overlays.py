"""
등록 전 육안 검수 자료 생성.

export 된 volume/GT 마스크를 사람이 눈으로 확인할 수 있게 오버레이 PNG 로 만든다.
**이 단계에서는 DB 에 아무것도 등록하지 않는다** — 검수를 통과한 케이스만 다음 단계에서 등록한다.

케이스마다 2행 × 3열 시트를 만든다:
    윗줄  : 병변 시작 / 대표 / 병변 끝 slice (전체 512×512)
    아랫줄: 같은 slice 를 병변 주변으로 확대 (병변이 작아 전체 뷰로는 정렬 확인이 어렵다)

표시용 정규화는 **volume 별 percentile 1~99% 클리핑 후 8bit** 이다.
이는 화면 표시 전용 규칙이며 **모델 입력 전처리(z-score)와 공유하지 않는다.**
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# UI 표시용 윈도잉 (모델 전처리와 무관)
DISPLAY_PERCENTILES = (1.0, 99.0)

PANEL = 340          # 시트 한 칸 크기
LABEL_H = 18
MASK_RGBA = (255, 80, 80, 90)     # 병변 채움 (반투명 빨강)
CONTOUR_RGB = (255, 235, 60)      # 병변 외곽선 (노랑)
ZOOM_MARGIN = 28                  # 확대 crop 여유 픽셀


def display_window(volume: np.ndarray) -> tuple[float, float]:
    """volume 전체 기준 percentile 1~99% 값. slice 마다 밝기가 튀지 않게 volume 단위로 고정한다."""
    lo, hi = np.percentile(volume, DISPLAY_PERCENTILES)
    if hi - lo < 1e-6:
        lo, hi = float(volume.min()), float(max(volume.max(), volume.min() + 1))
    return float(lo), float(hi)


def slice_to_8bit(slice_2d: np.ndarray, lo: float, hi: float) -> np.ndarray:
    clipped = np.clip(slice_2d, lo, hi)
    return ((clipped - lo) / (hi - lo) * 255.0).astype(np.uint8)


def _contour(mask: np.ndarray) -> np.ndarray:
    """마스크 경계 픽셀 (4방향 이웃 중 하나라도 배경이면 경계)."""
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    inner = (
        padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    )
    return mask & ~inner


def render_slice(volume: np.ndarray, gt: np.ndarray, index: int, lo: float, hi: float) -> Image.Image:
    base = slice_to_8bit(volume[:, :, index], lo, hi)
    rgb = Image.fromarray(np.stack([base] * 3, axis=-1), mode="RGB").convert("RGBA")

    mask = gt[:, :, index].astype(bool)
    if mask.any():
        overlay = np.zeros((*mask.shape, 4), dtype=np.uint8)
        overlay[mask] = MASK_RGBA
        edge = _contour(mask)
        overlay[edge] = (*CONTOUR_RGB, 255)
        rgb = Image.alpha_composite(rgb, Image.fromarray(overlay, mode="RGBA"))
    return rgb.convert("RGB")


def lesion_bbox(gt: np.ndarray) -> tuple[int, int, int, int]:
    """volume 전체 기준 병변 bounding box (row0, col0, row1, col1)."""
    rows = np.any(gt, axis=(1, 2))
    cols = np.any(gt, axis=(0, 2))
    r = np.nonzero(rows)[0]
    c = np.nonzero(cols)[0]
    return int(r.min()), int(c.min()), int(r.max()), int(c.max())


def build_sheet(case_id: str, volume: np.ndarray, gt: np.ndarray, out_dir: Path) -> dict:
    areas = gt.sum(axis=(0, 1))
    lesion = np.nonzero(areas)[0]
    if lesion.size == 0:
        raise RuntimeError("GT 마스크에 병변이 없습니다.")

    start, end = int(lesion.min()), int(lesion.max())
    representative = int(np.argmax(areas))
    picks = [("start", start), ("repr", representative), ("end", end)]

    lo, hi = display_window(volume)
    r0, c0, r1, c1 = lesion_bbox(gt)
    crop = (
        max(0, c0 - ZOOM_MARGIN),
        max(0, r0 - ZOOM_MARGIN),
        min(volume.shape[1], c1 + ZOOM_MARGIN),
        min(volume.shape[0], r1 + ZOOM_MARGIN),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (PANEL * 3, (PANEL + LABEL_H) * 2), (16, 18, 22))
    draw = ImageDraw.Draw(sheet)

    for col, (label, index) in enumerate(picks):
        rendered = render_slice(volume, gt, index, lo, hi)
        rendered.save(out_dir / f"{case_id}_slice{index:03d}_{label}.png")

        full = rendered.resize((PANEL, PANEL), Image.LANCZOS)
        zoom = rendered.crop(crop).resize((PANEL, PANEL), Image.NEAREST)

        x = col * PANEL
        sheet.paste(full, (x, LABEL_H))
        sheet.paste(zoom, (x, LABEL_H * 2 + PANEL))
        draw.text((x + 6, 4), f"{label} slice {index}  area={int(areas[index])}px", fill=(230, 230, 230))
        draw.text((x + 6, PANEL + LABEL_H + 4), f"zoom {label}", fill=(230, 230, 230))

    sheet_path = out_dir / f"{case_id}_review.png"
    sheet.save(sheet_path)

    return {
        "case_id": case_id,
        "display_window": [round(lo, 2), round(hi, 2)],
        "lesion_slice_start": start,
        "lesion_slice_end": end,
        "lesion_slice_count": int(lesion.size),
        "representative_slice": representative,
        "representative_area_px": int(areas.max()),
        "lesion_bbox_rowcol": [r0, c0, r1, c1],
        "sheet": sheet_path.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="등록 전 육안 검수용 오버레이 생성 (DB 등록 없음)")
    parser.add_argument("--export-root", type=Path, required=True, help="export_vs_seg_npy 출력 루트")
    parser.add_argument("--out", type=Path, required=True, help="검수 자료 출력 루트")
    parser.add_argument("--cases", nargs="*", help="생략 시 export-root 안의 모든 케이스")
    args = parser.parse_args()

    cases = args.cases or sorted(p.name for p in args.export_root.iterdir() if p.is_dir())
    summaries = []
    exit_code = 0

    for case_id in cases:
        case_dir = args.export_root / case_id
        print(f"=== {case_id} ===")
        try:
            volume = np.load(case_dir / "t1_volume.npy")
            gt = np.load(case_dir / "ground_truth_mask.npy")
            summary = build_sheet(case_id, volume, gt, args.out / case_id)
        except Exception as exc:
            print(f"  [실패] {exc}")
            exit_code = 1
            continue

        meta_path = case_dir / "export_meta.json"
        if meta_path.exists():
            summary["chosen_roi"] = json.loads(meta_path.read_text(encoding="utf-8")).get("chosen_roi")

        summaries.append(summary)
        print(f"  ROI={summary.get('chosen_roi')}  표시 윈도우={summary['display_window']}")
        print(
            f"  병변 slice {summary['lesion_slice_start']}~{summary['lesion_slice_end']} "
            f"({summary['lesion_slice_count']}장), 대표={summary['representative_slice']} "
            f"({summary['representative_area_px']}px)"
        )
        print(f"  bbox(row,col)={summary['lesion_bbox_rowcol']}")
        print(f"  검수 시트: {args.out / case_id / summary['sheet']}")

    (args.out / "review_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n요약: {args.out / 'review_summary.json'}  ({len(summaries)}건)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
