"""
질환 단위 문헌 학습정보 (API 계약 v0.4, `disease_info` 블록).

**케이스가 아니라 질환에 붙는 콘텐츠다.** 같은 질환의 케이스 6개가 같은 문헌 설명을 공유하므로,
케이스마다 복사하지 않고 여기 파일 하나를 읽어 응답을 만들 때 끼워 넣는다
(문헌을 고치면 DB 재등록 없이 모든 케이스에 반영된다).

  app/content/diseases/<disease_code>.json

manifest 로는 이 블록을 넣을 수 없다 (import_cases 가 거부한다). 케이스 등록자가
임의로 쓴 문장이 "문헌 기반"으로 표시되는 경로를 만들지 않기 위해서다.

**파일이 없거나 비어 있으면 `disease_info` 는 null 이고, content_levels 에서도 빠진다.**
지금(2026-09) VS-SEG 6케이스가 이 상태다 — 문헌 콘텐츠는 별도 단계에서 작성한다.

파일 형식
--------
    {
      "content_version": "vs-2026-09",
      "imaging_features": ["...", "..."],
      "medical_terms": [{"term": "소뇌교각(CPA)", "description": "..."}],
      "references": [{"title": "...", "publisher": "...", "url": "...", "accessed": "2026-09-08"}]
    }

`source` 와 `notice` 는 파일에 적지 않는다 — 아래 상수로 **항상 덮어쓴다.**
콘텐츠 작성자가 안내 문구를 빼거나 바꿀 수 없어야 하기 때문이다.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
CONTENT_DIR = APP_DIR / "content" / "diseases"

SOURCE = "literature_based"

# 화면 4 에 그대로 노출되는 문구. 문헌 일반론이 이 케이스의 소견으로 읽히면 안 된다.
NOTICE = (
    "아래 내용은 해당 질환에 대한 문헌 기반 학습정보이며, "
    "이 케이스의 개별 영상 소견을 확정하는 설명은 아닙니다."
)

# 파일 (존재여부, mtime, 크기) 를 함께 들고 있다가 바뀌면 다시 읽는다.
# 그래야 "파일만 고치면 서버 재시작 없이 반영된다"는 말이 실제로 맞는다.
_cache: dict[str, tuple[tuple, dict | None]] = {}


def content_path(disease_code: str) -> Path:
    return CONTENT_DIR / f"{disease_code}.json"


def _stamp(path: Path) -> tuple:
    try:
        stat = path.stat()
    except OSError:
        return (False, 0, 0)
    return (True, stat.st_mtime_ns, stat.st_size)


def clear_cache() -> None:
    """테스트에서 콘텐츠 폴더 자체를 바꿔치울 때 쓴다 (평소에는 mtime 으로 알아서 갱신된다)."""
    _cache.clear()


def load(disease_code: str | None) -> dict | None:
    """질환 문헌 정보. 파일이 없거나 내용이 비어 있으면 None."""
    if not disease_code:
        return None

    stamp = _stamp(content_path(disease_code))
    cached = _cache.get(disease_code)
    if cached is not None and cached[0] == stamp:
        return cached[1]

    content = _read(disease_code)
    _cache[disease_code] = (stamp, content)
    return content


def _read(disease_code: str) -> dict | None:
    path = content_path(disease_code)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("질환 문헌 콘텐츠를 읽지 못했습니다: %s", path)
        return None

    if not isinstance(raw, dict):
        logger.warning("질환 문헌 콘텐츠 형식이 객체가 아닙니다: %s", path)
        return None

    imaging_features = [s for s in raw.get("imaging_features", []) if str(s).strip()]
    medical_terms = _normalize_terms(raw.get("medical_terms", []))
    references = _normalize_references(raw.get("references", []))

    if not any([imaging_features, medical_terms, references]):
        logger.info("질환 문헌 콘텐츠가 비어 있어 disease_info 를 생략합니다: %s", path)
        return None

    return {
        # source / notice 는 파일 값을 쓰지 않고 항상 여기서 채운다
        "source": SOURCE,
        "notice": NOTICE,
        "imaging_features": imaging_features,
        "medical_terms": medical_terms,
        "references": references,
        "content_version": raw.get("content_version"),
    }


def _normalize_terms(items) -> list[dict]:
    terms = []
    for item in items or []:
        if isinstance(item, str) and item.strip():
            terms.append({"term": item.strip(), "description": ""})
        elif isinstance(item, dict) and str(item.get("term", "")).strip():
            terms.append(
                {"term": item["term"].strip(), "description": item.get("description", "")}
            )
    return terms


def _normalize_references(items) -> list[dict]:
    references = []
    for item in items or []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        references.append(
            {
                "title": item["title"].strip(),
                "publisher": item.get("publisher"),
                "url": item.get("url"),
                "accessed": item.get("accessed"),
            }
        )
    return references
