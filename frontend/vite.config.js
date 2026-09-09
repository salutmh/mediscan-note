import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

/**
 * 배포 빌드에 **localhost 가 박히는 것을 막는다.**
 *
 * `VITE_API_BASE` 는 빌드 시점에 번들 안으로 들어간다. `.env.production` 이 없으면
 * 기본값(`http://localhost:8010/api`)이 그대로 박히고, 그 dist 를 정적 호스팅에
 * 올리면 **아무 요청도 나가지 않는 화면**이 된다.
 *
 * 실제로 그런 상태였다 — E2E 가 전부 Vite dev 서버로만 돌아서 한 번도 안 걸렸다.
 *
 * 컴파일만 확인하려고 로컬에서 빌드할 때는 `VITE_ALLOW_LOCALHOST=1` 을 준다.
 * 배포용 빌드에서 이 값을 쓰면 안 된다.
 */
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '[::1]']

function assertDeployableApiBase(mode, env) {
  if (mode !== 'production') return
  if (env.VITE_ALLOW_LOCALHOST === '1') {
    console.warn(
      '[build] VITE_ALLOW_LOCALHOST=1 — 로컬 확인용 빌드입니다. 이 dist 를 배포하지 마세요.',
    )
    return
  }

  const base = (env.VITE_API_BASE ?? '').trim()
  if (!base) {
    throw new Error(
      'VITE_API_BASE 가 설정되지 않았습니다.\n' +
        '  배포용 빌드에는 실제 API 주소가 필요합니다 (예: https://api.example.com/api).\n' +
        '  frontend/.env.production 을 만들거나 환경변수로 넘기세요.\n' +
        '  로컬에서 컴파일만 확인하려면 VITE_ALLOW_LOCALHOST=1 을 주세요.',
    )
  }
  if (LOCAL_HOSTS.some((host) => base.includes(host))) {
    throw new Error(
      `VITE_API_BASE 가 로컬 주소입니다: ${base}\n` +
        '  이 dist 를 배포하면 브라우저가 자기 자신의 localhost 로 요청해 아무것도 동작하지 않습니다.\n' +
        '  로컬에서 컴파일만 확인하려면 VITE_ALLOW_LOCALHOST=1 을 주세요.',
    )
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  assertDeployableApiBase(mode, env)

  return {
    plugins: [vue()],
    test: {
      // 컴포넌트를 마운트해 실제 렌더 결과를 확인하므로 DOM 이 필요하다
      environment: 'jsdom',
      include: ['src/**/*.test.js'],
      // 테스트가 진짜 서버를 부르면 안 된다 — 호출은 전부 모킹한다
      globals: false,
    },
  }
})
