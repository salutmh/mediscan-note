"""
학습자 프로필 (시안 02-2 프로필·학교 / 03 기본정보 설정).

고정하려는 규칙:
  - **전부 선택 항목이다.** 비어 있는 것이 정상이고, 없어도 학습이 그대로 돌아간다
  - 보낸 키만 바꾼다 (부분 수정). 안 보낸 키는 건드리지 않는다
  - 빈 문자열은 **지우겠다**는 뜻이다 (`""` 를 그대로 저장하면
    "입력했는데 비었다"와 "입력하지 않았다"가 구분되지 않는다)
  - 의료 정보가 아니라 **학습자 배경**이다 — 여기에 진단·소견이 섞이면 안 된다
  - 탈퇴하면 함께 사라진다
"""
def test_profile_starts_empty(user_a):
    """가입 직후에는 비어 있다 — 채우라고 막지 않는다."""
    profile = user_a.get("/api/auth/me").json()["profile"]
    assert profile == {"job_role": None, "birth_date": None, "school": None, "major": None}


def test_it_saves_what_was_sent(user_a):
    response = user_a.patch(
        "/api/auth/me/profile",
        {"job_role": "radiology_student", "school": "메드렌즈대학교", "major": "방사선학과"},
    )
    assert response.status_code == 200

    profile = user_a.get("/api/auth/me").json()["profile"]
    assert profile["job_role"] == "radiology_student"
    assert profile["school"] == "메드렌즈대학교"
    assert profile["major"] == "방사선학과"
    # 보내지 않은 항목은 비어 있는 그대로다
    assert profile["birth_date"] is None


def test_it_only_changes_what_was_sent(user_a):
    """부분 수정. 한 항목을 고치려다 나머지가 지워지면 안 된다."""
    user_a.patch("/api/auth/me/profile", {"school": "A대학교", "major": "영상의학과"})
    user_a.patch("/api/auth/me/profile", {"major": "간호학과"})

    profile = user_a.get("/api/auth/me").json()["profile"]
    assert profile["school"] == "A대학교"
    assert profile["major"] == "간호학과"


def test_an_empty_string_clears_the_field(user_a):
    """**"입력했는데 비었다"는 상태를 만들지 않는다.** 빈 문자열은 null 로 저장한다."""
    user_a.patch("/api/auth/me/profile", {"school": "A대학교"})
    user_a.patch("/api/auth/me/profile", {"school": "   "})

    assert user_a.get("/api/auth/me").json()["profile"]["school"] is None


def test_profile_is_optional_for_learning(user_a, roi_mismatch):
    """프로필이 비어 있어도 **채점이 그대로 된다.** 여기서 막으면 안 된다."""
    response = user_a.post(
        "/api/cases/VS-SEG-202/submit", {"roi": roi_mismatch, "duration_seconds": 20}
    )
    assert response.status_code == 200
    assert response.json()["grade"] in {"match", "partial_match", "mismatch"}


def test_login_is_required(client):
    assert client.patch("/api/auth/me/profile", json={"school": "A"}).status_code == 401


def test_profile_is_removed_when_the_account_is_deleted(user_a):
    """탈퇴하면 배경 정보도 함께 사라진다 (users 행과 같이 지워진다)."""
    user_a.patch("/api/auth/me/profile", {"school": "지워질대학교"})
    response = user_a.delete("/api/auth/me", {"password": user_a.password})
    assert response.status_code == 200
    # 탈퇴 뒤에는 토큰도 무효다
    assert user_a.get("/api/auth/me").status_code == 401
