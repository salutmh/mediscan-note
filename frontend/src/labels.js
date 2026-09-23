/**
 * 코드 -> 화면 표기 라벨.
 *
 * 백엔드는 `brain_mri`, `vestibular_schwannoma` 같은 **코드**를 내려준다 (부위별 모델·다국어 확장을
 * 염두에 둔 계약이라 그대로 둔다). 사람이 읽는 문자열은 프론트에서만 만든다.
 * 매핑이 여러 화면에 흩어져 있으면 한 곳만 고쳐 다른 화면이 코드로 노출되므로 여기로 모았다.
 *
 * 모르는 코드는 **감추지 말고 코드 그대로** 보여준다 — 라벨 누락을 눈에 띄게 하기 위해서다.
 */
export const BODY_PART_LABEL = {
  brain_mri: '뇌 MRI',
  brain_ct: '뇌 CT',
  chest_xray: '흉부 X-ray',
  abdomen_ct: '복부 CT',
  knee_mri: '무릎 MRI',
}

export const DISEASE_LABEL = {
  vestibular_schwannoma: '전정신경초종',
  pneumothorax: '기흉',
  consolidation: '폐경화',
  nodule: '결절',
  pleural_effusion: '흉수',
  glioma: '교종',
  brain_metastasis: '뇌전이',
  ischemic_stroke: '허혈성 뇌졸중',
  multiple_sclerosis: '다발성경화증',
}

/**
 * 채점 결과 라벨.
 *
 * **"정답/오답"이라고 쓰지 않는다.** 우리는 의료인이 아니고, 이 화면이 말할 수 있는 것은
 * "전문가가 검수한 기준 마스크와 얼마나 겹쳤는가" 뿐이다 (CLAUDE.md 개발원칙 3).
 * 다만 "불일치" 는 학습자에게 차갑고 판정처럼 읽혀서, **무엇과 비교한 것인지**가
 * 드러나는 말로 쓴다 — 기준이 주어이면 사용자의 판단을 단정하지 않게 된다.
 *
 * `GRADE_LABEL` 은 문장·표에서 쓰는 전체 표기, `GRADE_BADGE` 는 뱃지처럼 폭이 좁은 자리용이다.
 * 셋을 색으로만 구분하지 않는다 — 어디서든 이 텍스트를 함께 쓴다.
 */
export const GRADE_LABEL = {
  match: '기준과 일치',
  partial_match: '일부 일치',
  mismatch: '기준과 다름',
}

export const GRADE_BADGE = {
  match: '일치',
  partial_match: '일부 일치',
  mismatch: '다름',
}

export function bodyPartLabel(code) {
  return BODY_PART_LABEL[code] ?? code
}

export function diseaseLabel(code) {
  return DISEASE_LABEL[code] ?? code
}

/**
 * case_id 에 질환 코드가 들어 있는가 (예: `glioma_06`).
 *
 * **제출 전에는 질환명이 곧 정답 힌트다.** 그런 case_id 는 판독 전 화면에서 그대로 보여주지 않고
 * 중립 라벨로 바꾼다 (CaseListView / ReadingView). API 의 case_id 자체는 바꾸지 않는다.
 */
export function caseIdRevealsDisease(caseId, disease = null) {
  const id = String(caseId ?? '').toLowerCase()
  if (!id) return false
  return [disease, ...Object.keys(DISEASE_LABEL)]
    .filter(Boolean)
    .some((code) => id.includes(String(code).toLowerCase()))
}

/**
 * 학습자 화면에 보일 케이스 이름. 질환 코드가 든 case_id 는 **끝 번호로 만든 중립 라벨**
 * (`glioma_06` -> "케이스 06")로 바꾼다. 번호를 case_id 에서 뽑으므로 목록·홈·대시보드·
 * 복습노트·진행현황 어디서나 같은 케이스는 같은 이름이다. 링크(router param)는 원래 case_id 를 쓴다.
 */
export function caseDisplayLabel(caseId, disease = null) {
  if (!caseIdRevealsDisease(caseId, disease)) return caseId
  const digits = String(caseId).match(/(\d+)(?!.*\d)/)?.[1]
  return digits ? `케이스 ${digits.padStart(2, '0')}` : '케이스'
}

export function gradeLabel(code) {
  return GRADE_LABEL[code] ?? code
}

export function gradeBadge(code) {
  return GRADE_BADGE[code] ?? code
}
