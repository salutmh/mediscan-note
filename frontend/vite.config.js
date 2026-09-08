import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  test: {
    // 컴포넌트를 마운트해 실제 렌더 결과를 확인하므로 DOM 이 필요하다
    environment: 'jsdom',
    include: ['src/**/*.test.js'],
    // 테스트가 진짜 서버를 부르면 안 된다 — 호출은 전부 모킹한다
    globals: false,
  },
})
