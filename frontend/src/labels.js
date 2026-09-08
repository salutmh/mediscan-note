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
}

export function bodyPartLabel(code) {
  return BODY_PART_LABEL[code] ?? code
}

export function diseaseLabel(code) {
  return DISEASE_LABEL[code] ?? code
}
