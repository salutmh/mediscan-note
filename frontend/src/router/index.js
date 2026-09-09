import { createRouter, createWebHistory } from 'vue-router'
import { authState } from '../stores/auth'

const routes = [
  // 홈 = 학습 대시보드. 예전에는 여기서 바로 /cases 로 넘겼는데, 그러면
  // 앱을 열었을 때 "내가 어디까지 했는지"가 어디에도 보이지 않았다.
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue'), meta: { requiresAuth: true } },
  // 화면 0
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  // 화면 1
  { path: '/cases', name: 'cases', component: () => import('../views/CaseListView.vue'), meta: { requiresAuth: true } },
  // 화면 2 (+ 제출 후 화면 3·4)
  {
    path: '/cases/:caseId',
    name: 'reading',
    component: () => import('../views/ReadingView.vue'),
    meta: { requiresAuth: true },
  },
  // 화면 6
  {
    path: '/wrong-notes',
    name: 'wrong-notes',
    component: () => import('../views/WrongNotesView.vue'),
    meta: { requiresAuth: true },
  },
  // 화면 6의 재도전 — 판독 훈련 화면을 재사용하고, 제출만 retry 엔드포인트로 보낸다
  {
    path: '/wrong-notes/:caseId/retry',
    name: 'retry',
    component: () => import('../views/ReadingView.vue'),
    meta: { requiresAuth: true, retry: true },
  },
  // 화면 5
  {
    path: '/analyze',
    name: 'analyze',
    component: () => import('../views/AnalyzeView.vue'),
    meta: { requiresAuth: true },
  },
  // 계정 설정 (회원 탈퇴). 민감정보를 다루는 서비스라 사용자가 자기 데이터를
  // 지울 경로가 화면에 있어야 한다.
  {
    path: '/account',
    name: 'account',
    component: () => import('../views/AccountView.vue'),
    meta: { requiresAuth: true },
  },
  // 운영자 화면 (최소 CMS) — 권한 차단은 서버가 한다 (403 ADMIN_REQUIRED).
  // 라우트를 숨기지 않는 이유: 프론트 숨김은 권한이 아니고, 권한 없는 사용자에게는
  // 화면이 "운영자 권한이 필요합니다"를 그대로 보여주는 편이 덜 혼란스럽다.
  {
    path: '/admin/cases',
    name: 'admin-cases',
    component: () => import('../views/AdminCasesView.vue'),
    meta: { requiresAuth: true },
  },
  // 케이스 후보 **기술 검수** 화면 (운영자 전용, 로컬 작업용).
  // 여기서 하는 것은 export 파이프라인 확인이지 의학적 검수가 아니다.
  {
    path: '/admin/review',
    name: 'admin-review',
    component: () => import('../views/CaseReviewView.vue'),
    meta: { requiresAuth: true },
  },
  // 화면 7
  {
    path: '/progress',
    name: 'progress',
    component: () => import('../views/MyProgressView.vue'),
    meta: { requiresAuth: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 나머지 API 가 전부 Bearer 토큰을 요구하므로, 토큰 없으면 화면 0으로 보낸다.
router.beforeEach((to) => {
  if (to.meta.requiresAuth && !authState.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && authState.token) {
    return { name: 'cases' }
  }
  return true
})
