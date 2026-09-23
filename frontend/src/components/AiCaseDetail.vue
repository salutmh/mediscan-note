<script setup>
import { computed, ref } from 'vue'
import { assetUrl } from '../api/medicalAiApi'

const props = defineProps({
  caseData: {
    type: Object,
    default: null,
  },
})

const showAiOverlay = ref(false)

const displayedImage = computed(() => {
  if (!props.caseData) return null

  if (showAiOverlay.value && props.caseData.ai_prediction?.overlay_url) {
    return assetUrl(props.caseData.ai_prediction.overlay_url)
  }

  return assetUrl(props.caseData.source_image_url)
})

function percent(value) {
  if (value == null) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}
</script>

<template>
  <section v-if="caseData" class="detail">
    <header class="detail__header">
      <div>
        <div class="eyebrow">Case</div>
        <h1>{{ caseData.case_id }}</h1>
        <p>{{ caseData.source_disease }}</p>
      </div>

      <button
        class="overlay-toggle"
        type="button"
        @click="showAiOverlay = !showAiOverlay"
      >
        {{ showAiOverlay ? '원본 영상 보기' : 'AI 참고 결과 보기' }}
      </button>
    </header>

    <div class="notice">
      AI 결과는 학습 보조용입니다. 학습자 채점은 전문가 기준 마스크 기준으로 처리합니다.
    </div>

    <div class="image-wrap">
      <img v-if="displayedImage" :src="displayedImage" alt="medical case">
    </div>

    <div class="info-grid">
      <div class="info-card">
        <strong>Expert GT</strong>
        <span>{{ caseData.gt_summary?.is_positive ? '병변 있음' : '병변 없음' }}</span>
        <small>객체 수 {{ caseData.gt_summary?.object_count ?? '-' }}</small>
      </div>

      <div class="info-card">
        <strong>AI prediction</strong>
        <span>{{ caseData.ai_prediction?.prediction_count ?? 0 }}개</span>
        <small>
          confidence threshold
          {{ caseData.ai_prediction?.confidence_threshold ?? '-' }}
        </small>
      </div>
    </div>

    <section class="predictions">
      <h3>AI 참고 결과</h3>

      <div v-if="!caseData.ai_prediction?.predictions?.length" class="empty">
        AI가 검출한 병변이 없습니다.
      </div>

      <article
        v-for="prediction in caseData.ai_prediction?.predictions || []"
        :key="prediction.prediction_id"
        class="prediction-card"
      >
        <div>
          <strong>{{ prediction.class_name }}</strong>
          <span>#{{ prediction.prediction_id }}</span>
        </div>

        <div class="confidence">
          모델 confidence score:
          <b>{{ percent(prediction.confidence_score) }}</b>
        </div>

        <img
          v-if="prediction.mask_url"
          class="mask-preview"
          :src="assetUrl(prediction.mask_url)"
          alt="AI predicted mask"
        >
      </article>
    </section>
  </section>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}

.detail__header h1 {
  margin: 4px 0 2px;
  font-size: 24px;
}

.detail__header p,
.eyebrow {
  margin: 0;
  opacity: 0.65;
}

.eyebrow {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.overlay-toggle {
  padding: 10px 14px;
  border: 1px solid #222;
  border-radius: 10px;
  background: white;
  cursor: pointer;
}

.notice {
  padding: 12px 14px;
  border-radius: 10px;
  background: #f5f5f5;
  font-size: 13px;
}

.image-wrap {
  min-height: 320px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  overflow: hidden;
  background: #111;
}

.image-wrap img {
  width: 100%;
  max-height: 620px;
  object-fit: contain;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.info-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border: 1px solid #ddd;
  border-radius: 12px;
}

.info-card small {
  opacity: 0.65;
}

.predictions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.predictions h3 {
  margin: 0;
}

.prediction-card {
  display: grid;
  grid-template-columns: 1fr auto 90px;
  align-items: center;
  gap: 16px;
  padding: 12px 14px;
  border: 1px solid #ddd;
  border-radius: 12px;
}

.prediction-card > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.prediction-card span {
  font-size: 12px;
  opacity: 0.55;
}

.confidence {
  font-size: 13px;
}

.mask-preview {
  width: 80px;
  height: 80px;
  object-fit: contain;
  background: #111;
  border-radius: 8px;
}

.empty {
  padding: 16px;
  border-radius: 10px;
  background: #f5f5f5;
  font-size: 14px;
}

@media (max-width: 760px) {
  .detail__header,
  .prediction-card {
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
