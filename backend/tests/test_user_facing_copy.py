"""
사용자에게 보이는 문구가 **제품을 잘못 설명하지 않는지** 확인한다.

==========================================================================
로그인 첫 화면이 "AI 기준과 비교해 학습하는 서비스" 라고 쓰여 있었다.
==========================================================================
사실이 아니다. 채점 기준은 **전문가가 검수한 reference mask** 이고,
AI 예측은 참고 정보로만 나간다 — AI 가 병변을 전혀 못 찾은 케이스에서도
학습자가 기준대로 칠하면 Dice 1.0 / `match` 가 나온다 (VS-SEG-204).

**첫 화면 문구가 제품을 잘못 설명하면, 학습자는 AI 를 정답으로 여기게 된다.**
그건 이 서비스가 지키려는 것의 정반대다.

여기서 하는 것은 코드 리뷰가 아니라 **문구 검사**다.
주석은 검사에서 뺀다 — 주석은 사용자에게 보이지 않고, 오히려 여기서
"왜 이렇게 썼는지"를 설명하는 자리이기 때문이다.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# 채점·학습 흐름을 다루는 화면. 화면 5(업로드 AI 분석)는 **실제로 AI 기능**이라 제외한다.
LEARNING_SCREENS = [
    "views/LoginView.vue",
    "views/HomeView.vue",
    "views/CaseListView.vue",
    "views/ReadingView.vue",
    "views/WrongNotesView.vue",
    "views/MyProgressView.vue",
    "components/ResultCompare.vue",
    "components/ExplanationPanel.vue",
]

# **AI 가 기준·정답이라고 읽히는 표현.**
FORBIDDEN = [
    ("AI 기준", "AI 는 기준이 아니다 — 기준은 전문가 검수 마스크다"),
    ("AI 정답", "AI 예측은 정답이 아니다"),
    ("AI가 채점", "채점은 기준 마스크로 한다"),
    ("AI 가 채점", "채점은 기준 마스크로 한다"),
    ("AI 진단", "이 서비스는 진단하지 않는다"),
    ("AI가 판단한 정답", "AI 예측은 참고 정보다"),
]

HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)


def _visible_text(path: Path) -> str:
    """주석을 뺀 원문. **주석은 사용자에게 보이지 않는다.**"""
    text = path.read_text(encoding="utf-8")
    text = HTML_COMMENT.sub(" ", text)
    text = BLOCK_COMMENT.sub(" ", text)
    return LINE_COMMENT.sub(" ", text)


@pytest.fixture(scope="module")
def screens() -> dict[str, str]:
    found = {}
    for rel in LEARNING_SCREENS:
        path = FRONTEND_SRC / rel
        if path.exists():
            found[rel] = _visible_text(path)
    return found


def test_the_screens_we_check_actually_exist(screens):
    """**검사기가 무엇을 봤는지 밝힌다.** 파일 이름이 바뀌면 검사가 조용히 놀게 된다."""
    missing = [rel for rel in LEARNING_SCREENS if rel not in screens]
    assert not missing, f"검사 대상 화면을 찾지 못했다: {missing} — 경로가 바뀌었는지 확인하라"
    assert len(screens) == len(LEARNING_SCREENS)


@pytest.mark.parametrize("phrase,why", FORBIDDEN)
def test_no_screen_calls_ai_the_grading_basis(screens, phrase, why):
    offenders = [rel for rel, text in screens.items() if phrase in text]
    assert not offenders, f"{offenders} 에 {phrase!r} 이 있다 — {why}"


def test_the_login_tagline_names_the_real_basis(screens):
    """첫 화면은 **무엇과 비교하는지**를 정확히 말해야 한다."""
    text = screens["views/LoginView.vue"]
    assert "전문가가 검수한 기준" in text, "채점 기준이 무엇인지 첫 화면에서 밝혀야 한다"


def test_the_upload_screen_may_still_say_ai():
    """화면 5 는 **실제로 AI 분석 기능**이다 — 거기서 AI 라고 쓰는 것은 정확하다.

    이 테스트는 위 금지어 검사가 **너무 넓게 번지지 않았는지** 확인한다.
    (모든 AI 언급을 막으면, 준비 중임을 알리는 정직한 안내까지 막힌다.)
    """
    analyze = FRONTEND_SRC / "views" / "AnalyzeView.vue"
    if not analyze.exists():
        pytest.skip("화면 5 가 없다")
    assert "views/AnalyzeView.vue" not in LEARNING_SCREENS
    assert "AI 분석" in analyze.read_text(encoding="utf-8")


# **부정형까지 잡으면 안 된다.**
# 처음에 "확정 진단"을 통째로 금지어로 넣었더니
# "AI 분석 결과는 학습 참고용이며 **확정 진단이 아닙니다**" 라는 면책 문구가 걸렸다 —
# 정확히 우리가 있기를 바라는 문장이다. 긍정형만 본다.
DIAGNOSIS_CLAIMS = [
    "확정 진단입니다",
    "확정 진단을 제공",
    "진단해 드립니다",
    "진단 결과입니다",
    "진단명은",
]


@pytest.mark.parametrize("phrase", DIAGNOSIS_CLAIMS)
def test_no_screen_promises_a_diagnosis(screens, phrase):
    """**진단 서비스로 오해될 표현을 쓰지 않는다.** 우리는 의료인이 아니다."""
    offenders = [rel for rel, text in screens.items() if phrase in text]
    assert not offenders, f"{offenders} 에 {phrase!r} 이 있다"


def test_the_disclaimer_itself_is_allowed(screens):
    """면책 문구는 **있어야 한다.** 위 검사가 그것까지 막으면 안 된다."""
    login = screens["views/LoginView.vue"]
    assert "확정 진단이 아닙니다" in login, "민감정보·비진단 고지가 첫 화면에 있어야 한다"


def test_grade_labels_avoid_right_or_wrong_wording(screens):
    """등급은 **기준과의 일치 정도**다.

    "정답/오답"으로 쓰면 확정적인 의학적 판단으로 읽힌다 (CLAUDE.md 개발원칙 3).
    """
    for rel, text in screens.items():
        for phrase in ("정답입니다", "오답입니다", "틀렸습니다"):
            assert phrase not in text, f"{rel} 에 {phrase!r} 이 있다"
