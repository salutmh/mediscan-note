/**
 * 헤드리스 Chrome 을 DevTools Protocol 로 직접 몰아서 화면 스크린샷을 찍는다.
 * (Claude in Chrome 확장이 연결 안 된 상태에서 UI 를 눈으로 확인하기 위한 임시 도구 — 프로젝트 코드가 아니다)
 *
 * 사용: node shoot.mjs <출력폴더>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9334)
const BASE = 'http://localhost:5173'
// 백엔드 주소는 프론트 .env 와 같아야 한다 (로컬 개발 기본 8010)
const API_BASE = process.env.MEDISCAN_API_BASE ?? 'http://localhost:8010/api'

mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function getWsUrl() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      const json = await res.json()
      if (json.webSocketDebuggerUrl) return json.webSocketDebuggerUrl
    } catch {
      /* 아직 안 떴음 */
    }
    await sleep(250)
  }
  throw new Error('헤드리스 Chrome 이 디버깅 포트를 열지 못했습니다')
}

// --- 최소한의 CDP 클라이언트 -------------------------------------------------
class Cdp {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.pending = new Map()
    this.sessionId = null
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      }
    })
  }

  send(method, params = {}) {
    this.id += 1
    const id = this.id
    const payload = { id, method, params }
    if (this.sessionId) payload.sessionId = this.sessionId
    this.ws.send(JSON.stringify(payload))
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id)
          reject(new Error(`CDP timeout: ${method}`))
        }
      }, 30000)
    })
  }
}

const wsUrl = await getWsUrl()
const ws = new WebSocket(wsUrl)
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve)
  ws.addEventListener('error', reject)
})
const cdp = new Cdp(ws)

// 탭 하나 붙잡기
const { targetInfos } = await cdp.send('Target.getTargets')
const page = targetInfos.find((t) => t.type === 'page')
const { sessionId } = await cdp.send('Target.attachToTarget', { targetId: page.targetId, flatten: true })
cdp.sessionId = sessionId

await cdp.send('Page.enable')
await cdp.send('Runtime.enable')
await cdp.send('Emulation.setDeviceMetricsOverride', {
  width: 1280,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
})

async function goto(path, { settle = 1400 } = {}) {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}

async function evaluate(expression) {
  const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (exceptionDetails) throw new Error(JSON.stringify(exceptionDetails))
  return result.value
}

async function shoot(name, { fullPage = true } = {}) {
  const params = { format: 'png', captureBeyondViewport: fullPage }
  if (fullPage) {
    const { cssContentSize } = await cdp.send('Page.getLayoutMetrics')
    params.clip = {
      x: 0,
      y: 0,
      width: cssContentSize.width,
      height: Math.min(cssContentSize.height, 2400),
      scale: 1,
    }
  }
  const { data } = await cdp.send('Page.captureScreenshot', params)
  const file = join(OUT, `${name}.png`)
  writeFileSync(file, Buffer.from(data, 'base64'))
  console.log(`저장: ${file}`)
}

const consoleErrors = []
await cdp.send('Log.enable').catch(() => {})
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data)
  if (msg.method === 'Log.entryAdded' && msg.params?.entry?.level === 'error') {
    consoleErrors.push(msg.params.entry.text)
  }
})

// ---------------------------------------------------------------- 촬영 시나리오
// 같은 Chrome 프로필을 재사용하므로 이전 실행의 토큰을 먼저 지운다 (로그인 화면이 리다이렉트되지 않게)
await goto('/login', { settle: 800 })
await evaluate("localStorage.clear(); 'cleared'")

// 1) 화면 0 — 로그인 (기본)
await goto('/login', { settle: 2000 })
await shoot('01-login')

// 2) 화면 0 — 회원가입 탭 (동의 폼 노출)
await evaluate(`
  (() => {
    const tabs = [...document.querySelectorAll('.segmented button')]
    const signup = tabs.find((b) => b.textContent.trim() === '회원가입')
    signup?.click()
    return !!signup
  })()
`)
await sleep(500)
await shoot('02-signup-consents')

// 3) 필수 동의 일부 체크한 상태 (진행 표시 확인)
await evaluate(`
  (async () => {
    const boxes = [...document.querySelectorAll('.consents .row:not(.all) input[type=checkbox]')]
    for (const b of boxes.slice(0, 3)) {
      b.click()
      await new Promise((r) => setTimeout(r, 60))
    }
    return boxes.length
  })()
`)
await sleep(400)
await shoot('03-consents-partial')

// 실제 가입해서 진짜 토큰을 받는다 (백엔드가 서명·만료를 검증하므로 위조 토큰은 통하지 않는다)
await evaluate(`
  (async () => {
    const email = 'shots' + Date.now() + '@example.com'
    const res = await fetch(${JSON.stringify(API_BASE)} + '/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email, password: 'pw1234', nickname: '온',
        consents: { agree_terms: true, agree_privacy: true, agree_sensitive_data: true,
                    agree_ai_notice: true, agree_age14: true, agree_marketing: false },
      }),
    })
    const data = await res.json()
    if (!data.access_token) return 'signup failed: ' + JSON.stringify(data)
    localStorage.setItem('mediscan.access_token', data.access_token)
    localStorage.setItem('mediscan.user', JSON.stringify({
      user_id: data.user_id, email: data.email, nickname: data.nickname,
    }))
    return 'signed up: ' + email
  })()
`).then((r) => console.log('   ', r))

// 4) 화면 1 — 케이스 목록
await goto('/cases', { settle: 1800 })
await shoot('04-cases')

// 5) 화면 2 — 판독 훈련 (제출 전)
await goto('/cases/VS-SEG-202', { settle: 2000 })
await shoot('05-reading')

// 6) ROI 를 캔버스에 그린 뒤 제출 -> 화면 3 + 화면 4
//    포인터 이벤트를 실제로 디스패치해서 브러시 궤적을 만든다 (종양 위치 근처)
await evaluate(`
  (async () => {
    const canvas = document.querySelector('canvas.overlay')
    if (!canvas) return 'no canvas'
    const rect = canvas.getBoundingClientRect()
    // 자리표시자 영상의 종양은 원본 좌표 (0.66w, 0.60h) 근처
    const cx = rect.left + rect.width * 0.66
    const cy = rect.top + rect.height * 0.60
    const opts = (x, y) => ({ pointerId: 1, bubbles: true, clientX: x, clientY: y, pointerType: 'mouse', isPrimary: true, button: 0 })
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}
    canvas.dispatchEvent(new PointerEvent('pointerdown', opts(cx - 12, cy - 8)))
    for (let i = -12; i <= 12; i += 3) {
      canvas.dispatchEvent(new PointerEvent('pointermove', opts(cx + i, cy + Math.sin(i / 5) * 6)))
      await new Promise((r) => setTimeout(r, 8))
    }
    canvas.dispatchEvent(new PointerEvent('pointerup', opts(cx + 12, cy + 8)))
    return 'drawn'
  })()
`).then((r) => console.log('ROI:', r))
await sleep(500)
await shoot('06-reading-roi')

await evaluate(`
  (() => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '제출')
    btn?.click()
    return btn ? 'submitted' : 'no submit button'
  })()
`).then((r) => console.log('제출:', r))
await sleep(2200)
await shoot('07-result-compare')

// 7) 화면 6 — 복습노트
await goto('/wrong-notes', { settle: 1600 })
await shoot('08-review-notes')

// 8) 화면 5 — 내 영상 분석 (업로드 전)
await goto('/analyze', { settle: 1600 })
await shoot('09-analyze-empty')

// 8-2) 화면 5 — 실제 파일을 업로드하고 영역 지정 후 분석까지
// 업로드할 이미지를 페이지 안에서 캔버스로 만들어 File 로 주입한다
// (네트워크에 의존하지 않고 실제 change 핸들러를 그대로 태운다)
await evaluate(`
  (async () => {
    const c = document.createElement('canvas')
    c.width = 512; c.height = 512
    const ctx = c.getContext('2d')
    ctx.fillStyle = '#111'; ctx.fillRect(0, 0, 512, 512)
    ctx.fillStyle = '#888'; ctx.beginPath(); ctx.ellipse(256, 256, 200, 220, 0, 0, Math.PI*2); ctx.fill()
    ctx.fillStyle = '#eee'; ctx.beginPath(); ctx.arc(338, 307, 32, 0, Math.PI*2); ctx.fill()
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'))
    const input = document.querySelector('input[type=file]')
    if (!input) return 'no file input'
    const dt = new DataTransfer()
    dt.items.add(new File([blob], 'my_scan.png', { type: 'image/png' }))
    input.files = dt.files
    input.dispatchEvent(new Event('change', { bubbles: true }))
    return 'uploaded'
  })()
`).then((r) => console.log('업로드:', r))
await sleep(1200)
await shoot('09b-analyze-uploaded')

await evaluate(`
  (async () => {
    const canvas = document.querySelector('canvas.overlay')
    if (!canvas) return 'no canvas'
    const rect = canvas.getBoundingClientRect()
    const cx = rect.left + rect.width * 0.66
    const cy = rect.top + rect.height * 0.60
    const opts = (x, y) => ({ pointerId: 1, bubbles: true, clientX: x, clientY: y, pointerType: 'mouse', isPrimary: true, button: 0 })
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}
    canvas.dispatchEvent(new PointerEvent('pointerdown', opts(cx - 10, cy - 6)))
    for (let i = -10; i <= 10; i += 3) {
      canvas.dispatchEvent(new PointerEvent('pointermove', opts(cx + i, cy + Math.sin(i / 4) * 5)))
      await new Promise((r) => setTimeout(r, 8))
    }
    canvas.dispatchEvent(new PointerEvent('pointerup', opts(cx + 10, cy + 6)))
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'AI 분석 요청')
    await new Promise((r) => setTimeout(r, 200))
    btn?.click()
    return btn ? 'analyzing' : 'no button'
  })()
`).then((r) => console.log('분석:', r))
await sleep(2200)
await shoot('09c-analyze-result')

// 9) 화면 7 — 진행현황
await goto('/progress', { settle: 1800 })
await shoot('10-progress')

// 10) 모바일 폭에서 판독 화면 (반응형 확인)
await cdp.send('Emulation.setDeviceMetricsOverride', {
  width: 420,
  height: 900,
  deviceScaleFactor: 1,
  mobile: true,
})
await goto('/cases/VS-SEG-202', { settle: 1800 })
await shoot('11-reading-mobile')

if (consoleErrors.length) {
  console.log('\n=== 콘솔 에러 ===')
  for (const e of consoleErrors.slice(0, 12)) console.log('  ' + e)
} else {
  console.log('\n콘솔 에러 없음')
}

ws.close()
