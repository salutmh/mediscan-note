<script setup>
/**
 * 화면 4 — 학습 해설 (api-spec.md v0.4, 4절 화면 4)
 *
 * 해설을 **출처가 다른 3개 블록**으로 나눠 보여준다. 하나로 뭉쳐 두면 학습자가
 * "이 케이스에서 확인된 것"과 "질환 일반론"을 구분할 수 없다.
 *
 *   case_facts    데이터셋 확인 정보 — 전문가 GT + DICOM 태그에서 계산된 사실
 *   disease_info  문헌 기반 학습정보 — 질환 일반 정보. 이 케이스의 소견이 아니다
 *   case_findings 전문가 검토 소견   — 전문가가 이 케이스를 보고 쓴 것
 *
 * 내부 값(dataset_verified 등)은 화면에 그대로 노출하지 않는다.
 * 없는 블록은 숨기지 않고 "등록되지 않았습니다"로 표시한다 — 없다는 것도 정보다.
 */
import { computed } from 'vue'

const props = defineProps({
  explanation: { type: Object, required: true },
})

const LATERALITY_LABEL = { right: '우측', left: '좌측' }

const facts = computed(() => props.explanation.case_facts ?? null)
const diseaseInfo = computed(() => props.explanation.disease_info ?? null)
const findings = computed(() => props.explanation.case_findings ?? null)

const lateralityLabel = computed(() => {
  const value = facts.value?.laterality
  return value ? (LATERALITY_LABEL[value] ?? value) : null
})

const lesionRange = computed(() => {
  const range = facts.value?.lesion_slice_range
  return Array.isArray(range) && range.length === 2 ? `${range[0]} ~ ${range[1]}` : null
})

function isUrl(value) {
  return typeof value === 'string' && /^https?:\/\//.test(value)
}
</script>

<template>
  <section class="card">
    <div class="card-title">
      <h2>학습 해설</h2>
    </div>

    <!-- 1) 이 케이스에서 확인된 사실 -->
    <section class="block">
      <div class="block-head">
        <span class="chip chip-dataset">데이터셋 확인 정보</span>
        <h3>이 케이스에서 확인된 사실</h3>
      </div>

      <template v-if="facts">
        <div class="disease">
          <span class="label">병명</span>
          <strong>{{ facts.disease_name }}</strong>
        </div>

        <dl class="rows">
          <div v-if="lateralityLabel" class="row">
            <dt>편측성</dt>
            <dd>
              <strong>{{ lateralityLabel }}</strong>
              <span v-if="facts.laterality_basis" class="muted note">
                {{ facts.laterality_basis }}
              </span>
            </dd>
          </div>
          <div class="row">
            <dt>기준 영역</dt>
            <dd>{{ facts.reference_region }}</dd>
          </div>
          <div v-if="facts.representative_slice !== null" class="row">
            <dt>대표 slice</dt>
            <dd>
              {{ facts.representative_slice }}
              <span v-if="facts.total_slices" class="muted note">
                원본 volume {{ facts.total_slices }}장 중 (0부터)
              </span>
            </dd>
          </div>
          <div v-if="lesionRange" class="row">
            <dt>병변 slice</dt>
            <dd>{{ lesionRange }}</dd>
          </div>
          <div v-if="facts.representative_area_px" class="row">
            <dt>기준 영역 면적</dt>
            <dd>{{ facts.representative_area_px.toLocaleString() }} px (대표 slice)</dd>
          </div>
          <div v-if="facts.dataset" class="row">
            <dt>출처</dt>
            <dd>{{ facts.dataset }}</dd>
          </div>
        </dl>
      </template>
      <p v-else class="muted">데이터셋 확인 정보가 등록되지 않았습니다.</p>
    </section>

    <!-- 2) 질환 문헌 정보 — 케이스 소견과 섞이지 않도록 시각적으로 분리한다 -->
    <section class="block literature">
      <div class="block-head">
        <span class="chip chip-literature">문헌 기반 학습정보</span>
        <h3>{{ facts?.disease_name ?? '질환' }} 일반 정보</h3>
      </div>

      <template v-if="diseaseInfo">
        <p class="notice">{{ diseaseInfo.notice }}</p>

        <dl class="rows">
          <div v-if="diseaseInfo.imaging_features?.length" class="row">
            <dt>일반적 MRI 특징</dt>
            <dd>
              <ul class="bullets">
                <li v-for="feature in diseaseInfo.imaging_features" :key="feature">
                  {{ feature }}
                </li>
              </ul>
            </dd>
          </div>
          <div v-if="diseaseInfo.medical_terms?.length" class="row">
            <dt>의학용어</dt>
            <dd>
              <ul class="terms">
                <li v-for="item in diseaseInfo.medical_terms" :key="item.term">
                  <strong>{{ item.term }}</strong>
                  <span v-if="item.description"> · {{ item.description }}</span>
                </li>
              </ul>
            </dd>
          </div>
          <div v-if="diseaseInfo.references?.length" class="row">
            <dt>참고문헌</dt>
            <dd>
              <ul class="references">
                <li v-for="ref in diseaseInfo.references" :key="ref.title">
                  <a v-if="isUrl(ref.url)" :href="ref.url" target="_blank" rel="noopener">
                    {{ ref.title }}
                  </a>
                  <span v-else>{{ ref.title }}</span>
                  <span v-if="ref.publisher" class="muted"> · {{ ref.publisher }}</span>
                  <span v-if="ref.accessed" class="muted"> · {{ ref.accessed }} 확인</span>
                </li>
              </ul>
            </dd>
          </div>
        </dl>
      </template>
      <p v-else class="muted">
        이 질환의 문헌 기반 학습정보가 아직 등록되지 않았습니다.
      </p>
    </section>

    <!-- 3) 이 케이스의 영상 소견 — 없을 때도 자리를 남긴다 -->
    <section class="block">
      <div class="block-head">
        <span class="chip chip-expert">전문가 검토 소견</span>
        <h3>이 케이스의 영상 소견</h3>
      </div>

      <template v-if="findings">
        <p class="findings">{{ findings.findings }}</p>
        <dl class="rows">
          <div v-if="findings.medical_terms?.length" class="row">
            <dt>의학용어</dt>
            <dd>
              <ul class="terms">
                <li v-for="item in findings.medical_terms" :key="item.term">
                  <strong>{{ item.term }}</strong>
                  <span v-if="item.description"> · {{ item.description }}</span>
                </li>
              </ul>
            </dd>
          </div>
          <div class="row">
            <dt>검토</dt>
            <dd>{{ findings.reviewer }} · {{ findings.reviewed_at }}</dd>
          </div>
        </dl>
      </template>
      <p v-else class="muted">
        이 케이스의 개별 영상 소견은 등록되어 있지 않습니다.
        전문가 검토가 이루어지면 이 자리에 검토자·검토일과 함께 추가됩니다.
      </p>
    </section>
  </section>
</template>

<style scoped>
.block {
  padding-top: var(--sp-4);
  margin-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.block:first-of-type {
  padding-top: 0;
  margin-top: 0;
  border-top: 0;
}

.block-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}

.block-head h3 {
  margin: 0;
  font-size: 14px;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.chip {
  padding: 2px 9px;
  border-radius: var(--r-full);
  font-size: 11.5px;
  font-weight: 700;
  border: 1px solid transparent;
}

.chip-dataset {
  background: var(--match-bg);
  border-color: var(--match-line);
  color: var(--match-ink);
}

.chip-literature {
  background: var(--brand-50);
  border-color: var(--brand-100);
  color: var(--brand-700);
}

.chip-expert {
  background: var(--gray-50);
  border-color: var(--line);
  color: var(--ink-muted);
}

/* 문헌 블록은 배경면을 달리해 케이스 소견과 섞여 보이지 않게 한다 */
.literature {
  padding: var(--sp-4);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-sunken);
}

.notice {
  margin: 0 0 var(--sp-3);
  padding: var(--sp-3);
  border-radius: var(--r-sm, 6px);
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  color: var(--ink-secondary);
  font-size: 12.5px;
  line-height: 1.6;
}

.disease {
  padding: var(--sp-4);
  margin-bottom: var(--sp-4);
  border-radius: var(--r-md);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
}

.disease .label {
  display: block;
  color: var(--brand-700);
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0;
  opacity: 0.75;
  margin-bottom: 2px;
}

.disease strong {
  font-size: 17px;
  letter-spacing: -0.02em;
  color: var(--brand-700);
}

.findings {
  margin: 0;
  font-size: 14px;
  line-height: 1.65;
  color: var(--ink-secondary);
}

.rows {
  margin: 0;
}

.row {
  display: flex;
  gap: var(--sp-4);
  align-items: flex-start;
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--line);
}

.row:first-child {
  border-top: 0;
  padding-top: 0;
}

dt {
  flex: 0 0 92px;
  color: var(--ink-muted);
  font-size: 12.5px;
  font-weight: 600;
  padding-top: 2px;
}

dd {
  margin: 0;
  flex: 1;
  font-size: 14px;
  line-height: 1.65;
  color: var(--ink-secondary);
}

.note {
  display: block;
  font-size: 12.5px;
  margin-top: 2px;
}

.bullets,
.references {
  margin: 0;
  padding-left: 18px;
}

.bullets li,
.references li {
  margin-bottom: 4px;
}

.terms {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  font-size: 13px;
}

@media (max-width: 560px) {
  .row {
    flex-direction: column;
    gap: 4px;
  }

  dt {
    flex: none;
  }
}
</style>
