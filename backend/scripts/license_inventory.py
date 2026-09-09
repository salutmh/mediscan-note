"""
의존성·자산 라이선스 목록 만들기.

**라이선스를 판단하지 않는다.** 무엇을 쓰고 있고 각각 어떤 라이선스라고 적혀 있는지를
모아서 보여줄 뿐이다. "써도 되는가"는 사람이 판단할 문제이고, 특히 **의료 데이터셋과
모델 가중치는 코드 라이선스와 전혀 다른 문제**다 (BLOCKER-1).

왜 필요한가
----------
저장소를 Public 으로 돌렸고 Closed Beta 로 외부 사용자에게 열려고 한다. 그때 필요한 것은
"우리가 무엇을 쓰고 있는지"의 목록이다. 목록이 없으면 검토를 시작할 수조차 없다.

무엇을 모으는가
--------------
  파이썬 패키지    requirements.txt 에 적힌 것 + 실제 설치본의 라이선스 메타데이터
  프론트 패키지    package.json + node_modules 의 license 필드
  코드 아닌 자산   의료 데이터셋 · 모델 가중치 · 폰트 — **사람 검토 항목으로 남긴다**

주의해서 볼 것으로 표시하는 것
-----------------------------
  GPL / LGPL / AGPL      배포 형태에 따라 의무가 생길 수 있다
  라이선스 미상          확인이 필요하다 ("문제 없음"이 아니다)
  코드 아닌 자산         코드 라이선스와 다른 조건이 붙는다

사용법
------
    cd backend
    python -m scripts.license_inventory
    python -m scripts.license_inventory --json ../docs/license-inventory.json
    python -m scripts.license_inventory --markdown ../docs/DEPENDENCIES.md
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 배포 형태에 따라 의무가 생길 수 있는 라이선스. **금지 목록이 아니다** — 확인 목록이다.
ATTENTION_PATTERNS = re.compile(r"\b(GPL|AGPL|LGPL|SSPL|CC[- ]BY[- ]NC|Proprietary)\b", re.I)
UNKNOWN = "확인 필요"

# 코드가 아닌 자산. **자동으로 판단할 수 없다** — 사람이 원 출처의 조건을 봐야 한다.
NON_CODE_ASSETS = [
    {
        "name": "VS-SEG (Vestibular Schwannoma Segmentation) 데이터셋",
        "kind": "의료영상 데이터셋",
        "used_for": "학습 케이스의 영상과 전문가 GT(RTSTRUCT)",
        "in_repo": False,
        "note": (
            "원본 DICOM 과 파생 npy·PNG 는 저장소에 커밋하지 않는다 "
            "(backend/data/, app/static/cases/ 는 gitignore). "
            "다만 **외부 사용자에게 서비스로 보여주는 것**은 별도 문제다."
        ),
        "status": "NEEDS_LICENSE_REVIEW",
        "blocker": "BLOCKER-1",
    },
    {
        "name": "VS_Seg 사전학습 가중치 (UNet2d5_spvPA)",
        "kind": "모델 가중치",
        "used_for": "AI 예측 sidecar 계산 (참고 정보 전용, 채점에 쓰지 않음)",
        "in_repo": False,
        "note": (
            "가중치 파일(.pth)은 저장소에 없다. 계산된 예측 지표만 sidecar 로 서비스한다. "
            "재배포가 아니라 **결과 활용**이므로 조건이 다를 수 있다 — 확인이 필요하다."
        ),
        "status": "NEEDS_LICENSE_REVIEW",
        "blocker": "BLOCKER-1",
    },
    {
        "name": "Pretendard 폰트",
        "kind": "폰트",
        "used_for": "프론트 타이포그래피",
        "in_repo": False,
        "note": "npm 패키지로 들어온다 (아래 프론트 목록에도 나온다). SIL Open Font License.",
        "status": "확인됨",
        "blocker": None,
    },
]


def _normalise(value) -> str:
    if not value:
        return UNKNOWN
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "none", "unlicense d"}:
        return UNKNOWN
    # "License :: OSI Approved :: MIT License" -> "MIT License"
    if "::" in text:
        text = text.split("::")[-1].strip()
    return text[:80]


def python_packages() -> list[dict]:
    """requirements.txt 에 적힌 것 + 실제 설치본의 메타데이터."""
    import importlib.metadata as md

    requirements = BACKEND_DIR / "requirements.txt"
    declared: list[tuple[str, str]] = []
    if requirements.exists():
        for line in requirements.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            name = re.split(r"[=<>!\[]", line, 1)[0].strip()
            declared.append((name, line))

    rows = []
    for name, spec in declared:
        entry = {"name": name, "declared": spec, "version": UNKNOWN, "license": UNKNOWN}
        try:
            meta = md.metadata(name)
        except Exception:
            entry["license"] = UNKNOWN
            entry["note"] = "설치본을 찾지 못했다 (pip install 이 안 된 환경일 수 있다)"
            rows.append(entry)
            continue

        entry["version"] = meta["Version"]
        license_text = _normalise(meta.get("License"))
        if license_text == UNKNOWN:
            classifiers = [
                c for c in (meta.get_all("Classifier") or []) if c.startswith("License")
            ]
            if classifiers:
                license_text = _normalise(classifiers[0])
        if license_text == UNKNOWN:
            # 최신 패키지는 License-Expression 을 쓴다
            license_text = _normalise(meta.get("License-Expression"))
        entry["license"] = license_text
        entry["homepage"] = meta.get("Home-page") or meta.get("Project-URL") or ""
        rows.append(entry)
    return rows


def node_packages() -> list[dict]:
    """package.json 에 적힌 것 + node_modules 의 license 필드."""
    package_json = REPO_DIR / "frontend" / "package.json"
    if not package_json.exists():
        return []
    data = json.loads(package_json.read_text(encoding="utf-8"))
    modules = REPO_DIR / "frontend" / "node_modules"

    rows = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            entry = {
                "name": name,
                "declared": spec,
                "section": section,
                "version": UNKNOWN,
                "license": UNKNOWN,
            }
            manifest = modules / name / "package.json"
            if manifest.exists():
                try:
                    info = json.loads(manifest.read_text(encoding="utf-8"))
                    entry["version"] = info.get("version", UNKNOWN)
                    license_field = info.get("license") or info.get("licenses")
                    if isinstance(license_field, list) and license_field:
                        license_field = license_field[0]
                    if isinstance(license_field, dict):
                        license_field = license_field.get("type")
                    entry["license"] = _normalise(license_field)
                    entry["homepage"] = info.get("homepage", "")
                except Exception:
                    entry["note"] = "package.json 을 읽지 못했다"
            else:
                entry["note"] = "node_modules 에 없다 (npm install 전일 수 있다)"
            rows.append(entry)
    return rows


def needs_attention(entry: dict) -> str | None:
    """확인이 필요한 이유. 없으면 None. **금지 판정이 아니다.**"""
    license_text = entry.get("license", UNKNOWN)
    if license_text == UNKNOWN:
        return "라이선스를 확인하지 못했다"
    if ATTENTION_PATTERNS.search(license_text):
        return f"배포 형태에 따라 의무가 생길 수 있다 ({license_text})"
    return None


def build_inventory() -> dict:
    python_rows = python_packages()
    node_rows = node_packages()

    attention = []
    for entry in python_rows + node_rows:
        reason = needs_attention(entry)
        if reason:
            attention.append({**entry, "reason": reason})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "이 목록은 **무엇을 쓰고 있는지**를 모은 것입니다. "
            "'써도 되는가' 는 판단하지 않습니다 — 사람이 검토할 자료입니다."
        ),
        "counts": {
            "python": len(python_rows),
            "node": len(node_rows),
            "attention": len(attention),
            "non_code_assets": len(NON_CODE_ASSETS),
        },
        "python": python_rows,
        "node": node_rows,
        "attention": attention,
        "non_code_assets": NON_CODE_ASSETS,
        "unresolved_blockers": sorted(
            {a["blocker"] for a in NON_CODE_ASSETS if a.get("blocker")}
        ),
    }


def to_markdown(inv: dict) -> str:
    lines = [
        "# 의존성·자산 라이선스 목록",
        "",
        "> `python -m scripts.license_inventory --markdown docs/DEPENDENCIES.md` 로 생성됩니다.",
        "> **이 문서는 라이선스를 판단하지 않습니다.** 무엇을 쓰고 있는지를 모은 자료이고,",
        "> '써도 되는가' 는 사람이 검토할 문제입니다.",
        "",
        f"생성 시각: {inv['generated_at']}",
        "",
        "---",
        "",
        "## 0. 코드가 아닌 자산 (가장 먼저 볼 것)",
        "",
        "**코드 라이선스와 전혀 다른 문제다.** 의료 데이터셋과 모델 가중치는 조건이 별도로 붙는다.",
        "",
        "| 항목 | 종류 | 쓰임 | 저장소 포함 | 상태 |",
        "|---|---|---|---|---|",
    ]
    for asset in inv["non_code_assets"]:
        blocker = " ({})".format(asset["blocker"]) if asset.get("blocker") else ""
        in_repo = "예" if asset["in_repo"] else "아니오"
        lines.append(
            "| {} | {} | {} | {} | **{}**{} |".format(
                asset["name"], asset["kind"], asset["used_for"],
                in_repo, asset["status"], blocker,
            )
        )
    lines.append("")
    for asset in inv["non_code_assets"]:
        lines.append(f"- **{asset['name']}** — {asset['note']}")
    if inv["unresolved_blockers"]:
        lines += [
            "",
            f"> 미해결: {', '.join(inv['unresolved_blockers'])} "
            "(`docs/CLAUDE_HANDOFF.md` 하단 BLOCKERS 참고)",
        ]

    lines += [
        "",
        "---",
        "",
        "## 1. 확인이 필요한 항목",
        "",
    ]
    if inv["attention"]:
        lines += ["| 패키지 | 버전 | 라이선스 | 이유 |", "|---|---|---|---|"]
        for entry in inv["attention"]:
            lines.append(
                f"| `{entry['name']}` | {entry['version']} | {entry['license']} | {entry['reason']} |"
            )
        lines += [
            "",
            "> **금지 목록이 아니다.** 배포 형태(서버에서 실행 / 재배포 / 정적 링크)에 따라",
            "> 의무가 달라지므로 확인이 필요하다는 뜻이다.",
        ]
    else:
        lines.append("확인이 필요한 항목이 없습니다.")

    for section, title in (("python", "2. 백엔드 (Python)"), ("node", "3. 프론트엔드 (npm)")):
        lines += ["", "---", "", f"## {title}", "", "| 패키지 | 버전 | 라이선스 |", "|---|---|---|"]
        for entry in sorted(inv[section], key=lambda e: e["name"].lower()):
            lines.append(f"| `{entry['name']}` | {entry['version']} | {entry['license']} |")

    lines += [
        "",
        "---",
        "",
        "## 4. 이 프로젝트의 라이선스",
        "",
        "저장소 루트에 LICENSE 파일이 없다면 **아직 정하지 않은 것**이다.",
        "Public 저장소라도 라이선스가 없으면 기본적으로 모든 권리가 유보된다.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="의존성·자산 라이선스 목록 (판단하지 않고 모으기만 한다)"
    )
    parser.add_argument("--json", help="JSON 저장 경로")
    parser.add_argument("--markdown", help="Markdown 저장 경로")
    args = parser.parse_args()

    inv = build_inventory()
    counts = inv["counts"]

    print(f"백엔드 {counts['python']}개 / 프론트 {counts['node']}개")
    print()

    if inv["attention"]:
        print(f"확인이 필요한 항목 {counts['attention']}건:")
        for entry in inv["attention"]:
            print(f"  {entry['name']:22} {entry['license']:28} {entry['reason']}")
    else:
        print("확인이 필요한 패키지 없음")

    print()
    print("코드가 아닌 자산 (사람이 판단해야 하는 것):")
    for asset in inv["non_code_assets"]:
        mark = "!" if asset["status"] == "NEEDS_LICENSE_REVIEW" else "-"
        blocker = f" [{asset['blocker']}]" if asset.get("blocker") else ""
        print(f"  {mark} {asset['name']} — {asset['status']}{blocker}")

    # LICENSE 파일 확인
    has_license = any((REPO_DIR / name).exists() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"))
    print()
    if has_license:
        print("저장소 LICENSE 파일: 있음")
    else:
        print("저장소 LICENSE 파일: **없음** — Public 이지만 라이선스를 정하지 않은 상태입니다.")
        print("  라이선스가 없으면 기본적으로 모든 권리가 유보됩니다 (사용자 결정 필요).")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장: {args.json}")
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(to_markdown(inv), encoding="utf-8", newline="\n")
        print(f"Markdown 저장: {args.markdown}")

    print()
    print("※ 이 목록은 라이선스를 판단하지 않습니다. 사람이 검토할 자료입니다.")
    # 확인이 필요한 항목이 있다고 실패로 처리하지 않는다 — 판단은 사람 몫이다
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
