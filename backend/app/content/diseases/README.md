# 질환 문헌 학습정보 (`disease_info`)

파일 이름은 `cases.disease` 코드와 같아야 한다: `<disease_code>.json`
(예: `vestibular_schwannoma.json`).

**여기 없는 질환은 `disease_info` 가 null 로 나가고 `content_levels` 에서도 빠진다.**
비어 있는 파일도 마찬가지다 - 빈 카드가 화면에 뜨는 것보다 없는 편이 정확하다.

## 형식

```json
{
  "content_version": "vs-2026-09",
  "imaging_features": ["...", "..."],
  "medical_terms": [{ "term": "...", "description": "..." }],
  "references": [{ "title": "...", "publisher": "...", "url": "...", "accessed": "2026-09-08" }]
}
```

`source` 와 `notice` 는 파일에 적지 않는다. `app/disease_content.py` 가 항상 덮어쓴다
(안내 문구를 콘텐츠 작성자가 빼거나 바꿀 수 없어야 한다).

## 작성 규칙

- **이 질환의 일반적인 특징만** 쓴다. "이 케이스에서 관찰된다"고 단정하는 문장은 쓰지 않는다.
  개별 케이스 소견은 `case_findings`(전문가 검토) 자리이고, 여기가 아니다.
- 문장은 **실제로 확인한 문헌**에 근거해야 한다. `references` 에 출처를 남긴다.
- 이 폴더의 내용은 텍스트뿐이라 git 에 커밋한다 (의료영상과 달리 개인정보가 없고,
  출처가 바뀌면 diff 로 확인할 수 있다).

## 현재 상태 (2026-09)

`vestibular_schwannoma.json` 1건 작성 완료. VS-SEG 6케이스는
`content_levels: ["dataset_verified", "literature_based"]` 로 동작한다.
(케이스별 소견 `case_findings` 는 전문가 검토 전이라 아직 `null` 이다.)
