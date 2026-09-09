/**
 * 오류 경로 검증 (v0.8) — **사용자가 잘못됐을 때 무엇을 보는가.**
 *
 * 정상 흐름은 기존 E2E 가 본다. 여기서 보는 것은 반대쪽이다:
 *
 *   1) 없는 케이스로 들어갔을 때 — 흐름이 막히지 않고 안내가 나오는가
 *   2) 로그인 실패 — 사유를 사람이 읽을 수 있는가 (가입 여부를 흘리지 않는가)
 *   3) 토큰이 무효해졌을 때 — 로그인 화면으로 돌아가는가 (401 재진입 없이)
 *   4) 백엔드가 죽었을 때 — **개발자용 안내가 아니라 사용자용 문구가 나오는가**
 *   5) 권한 없이 운영자 화면 — 왜 안 되는지 알려주는가
 *   6) 아무 입력 없이 제출 — 버튼이 막혀 있는가
 *
 * 4번이 특히 중요하다. 예전에는 모든 화면의 모든 요청 실패에
 * "backend 폴더에서 uvicorn ... 이 실행 중인지 확인하세요" 가 나왔다.
 *
 * 사용: node error-paths.mjs <출력폴더> <디버깅포트>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9333)
const BASE = 'http://localhost:5173'
const API = 'http://localhost:8010'
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const failures = []
const check = (ok, label, detail = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

async function getWsUrl() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const json = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()
      if (json.webSocketDebuggerUrl) return json.webSocketDebuggerUrl
    } catch {}
    await sleep(250)
  }
  throw new Error('헤드리스 Chrome 디버깅 포트 없음')
}

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

const ws = new WebSocket(await getWsUrl())
await new Promise((res, rej) => {
  ws.addEventListener('open', res)
  ws.addEventListener('error', rej)
})
const cdp = new Cdp(ws)
const { targetInfos } = await cdp.send('Target.getTargets')
const page = targetInfos.find((t) => t.type === 'page')
const { sessionId } = await cdp.send('Target.attachToTarget', {
  targetId: page.targetId,
  flatten: true,
})
cdp.sessionId = sessionId
await cdp.send('Page.enable')
await cdp.send('Runtime.enable')
await cdp.send('Network.enable')
await cdp.send('Emulation.setDeviceMetricsOverride', {
  width: 1280,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
})

const evaluate = async (expression) => {
  const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (exceptionDetails) throw new Error(JSON.stringify(exceptionDetails))
  return result.value
}
const goto = async (path, settle = 2200) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}
const shoot = async (name) => {
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
}
const bodyText = () => evaluate(`document.body.innerText.replace(/\\s+/g, ' ')`)

// ------------------------------------------------------------ 준비
const email = `err${Date.now()}@example.com`
await goto('/login')
const token = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/auth/signup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: ${JSON.stringify(email)}, password: 'pw12345678', nickname: '오류경로',
        consents: { agree_terms: true, agree_privacy: true, agree_sensitive_data: true,
                    agree_ai_notice: true, agree_age14: true, agree_marketing: false },
      }),
    })
    const d = await res.json()
    if (!d.access_token) return 'FAIL ' + JSON.stringify(d).slice(0, 200)
    localStorage.setItem('mediscan.access_token', d.access_token)
    localStorage.setItem('mediscan.user', JSON.stringify({
      user_id: d.user_id, email: d.email, nickname: d.nickname }))
    return d.access_token
  })()
`)
if (String(token).startsWith('FAIL')) {
  console.log(`가입 실패 — ${token}`)
  process.exit(1)
}

// -------------------------------------------------- 1) 없는 케이스
console.log('1) 없는 케이스로 직접 들어갔을 때')
await goto('/cases/DOES-NOT-EXIST-999', 3000)
const missing = await bodyText()
check(
  /등록되지 않|찾을 수 없|없습니다/.test(missing),
  '없는 케이스라고 알려준다',
  missing.slice(0, 80),
)
check(
  /케이스 목록|목록으로/.test(missing),
  '돌아갈 길을 준다 (막다른 화면이 아니다)',
)
check(!/Traceback|undefined|\[object/.test(missing), '내부 오류가 화면에 새지 않는다')
await shoot('e01-missing-case')

// -------------------------------------------------- 2) 로그인 실패
console.log('2) 로그인 실패')
await evaluate(`(() => { localStorage.clear(); return 'cleared' })()`)
await goto('/login', 2000)
await evaluate(`
  (async () => {
    const inputs = [...document.querySelectorAll('input')]
    const setValue = (el, v) => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(el, v)
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    setValue(inputs.find((i) => i.type === 'email' || i.type === 'text'), 'nobody@example.com')
    setValue(inputs.find((i) => i.type === 'password'), 'wrong-password-1')
    const form = document.querySelector('form')
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    return 'submitted'
  })()
`)
await sleep(2500)
const loginFail = await bodyText()
check(
  /올바르지 않|일치하지 않/.test(loginFail),
  '로그인 실패 사유를 사람이 읽을 수 있다',
  (loginFail.match(/[^.]*올바르지 않[^.]*\./) ?? [''])[0].slice(0, 60),
)
check(
  !/가입되지 않은|존재하지 않는 계정|없는 이메일/.test(loginFail),
  '**가입 여부를 흘리지 않는다**',
)
check(!/401|INVALID_CREDENTIALS/.test(loginFail), '에러 코드가 사용자에게 노출되지 않는다')
await shoot('e02-login-failed')

// -------------------------------------------------- 3) 무효 토큰
console.log('3) 토큰이 무효해졌을 때')
await evaluate(`
  (() => {
    localStorage.setItem('mediscan.access_token', 'clearly.invalid.token')
    localStorage.setItem('mediscan.user', JSON.stringify({ user_id: 'u_x', nickname: 'x' }))
    return 'set'
  })()
`)
const errorsBefore = []
await cdp.send('Log.enable').catch(() => {})
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.method === 'Log.entryAdded' && m.params?.entry?.level === 'error') {
    errorsBefore.push(m.params.entry.text)
  }
})

// 401 요청 수를 센다 — 재진입하면 여러 번 나간다
const unauthorized = []
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.method === 'Network.responseReceived' && m.params?.response?.status === 401) {
    unauthorized.push(m.params.response.url)
  }
})

await goto('/cases', 3500)
const afterInvalid = await evaluate(`
  (() => ({
    path: location.pathname,
    token: localStorage.getItem('mediscan.access_token'),
    text: document.body.innerText.replace(/\\s+/g, ' ').slice(0, 200),
  }))()
`)
check(afterInvalid.path === '/login', '로그인 화면으로 돌려보낸다', afterInvalid.path)
check(afterInvalid.token === null, '무효 토큰을 지운다')
check(
  unauthorized.length <= 3,
  '**401 재진입 루프가 없다**',
  `401 응답 ${unauthorized.length}회`,
)
await shoot('e03-invalid-token')

// -------------------------------------------------- 4) 백엔드 없음
console.log('4) 백엔드에 연결할 수 없을 때')
await goto('/login', 1500)
// 실제 서버를 죽이지 않고 fetch 를 실패시킨다 (다른 검증에 영향을 주지 않기 위해)
const offlineText = await evaluate(`
  (async () => {
    const original = window.fetch
    window.fetch = () => Promise.reject(new TypeError('Failed to fetch'))
    try {
      const mod = await import('/src/api/client.js')
      await mod.apiFetch('/cases')
      return 'NO_ERROR'
    } catch (e) {
      return e.message
    } finally {
      window.fetch = original
    }
  })()
`)
check(offlineText !== 'NO_ERROR', '연결 실패가 오류로 전달된다')
check(!/uvicorn|backend 폴더|app\\.main/.test(offlineText), '**개발자용 실행 안내가 나오지 않는다**', offlineText)
check(/연결|인터넷/.test(offlineText), '사용자가 무엇을 확인할지 알려준다', offlineText)
check(/다시 시도/.test(offlineText), '다시 시도해도 된다는 것을 알려준다')

// -------------------------------------------------- 5) 권한 없음
console.log('5) 권한 없이 운영자 화면')
await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/auth/signup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'noadmin' + Date.now() + '@example.com', password: 'pw12345678', nickname: '일반',
        consents: { agree_terms: true, agree_privacy: true, agree_sensitive_data: true,
                    agree_ai_notice: true, agree_age14: true, agree_marketing: false },
      }),
    })
    const d = await res.json()
    localStorage.setItem('mediscan.access_token', d.access_token)
    localStorage.setItem('mediscan.user', JSON.stringify({ user_id: d.user_id, nickname: d.nickname }))
    return 'ok'
  })()
`)
await goto('/admin/cases', 3000)
const forbidden = await bodyText()
check(/운영자 권한|권한이 필요/.test(forbidden), '왜 안 되는지 알려준다', forbidden.slice(0, 70))
check(/grant_admin/.test(forbidden), '어떻게 얻는지도 알려준다 (운영자 화면이라 내부 명령이 적절하다)')
await shoot('e05-forbidden')

// -------------------------------------------------- 6) 빈 제출
console.log('6) 아무것도 그리지 않고 제출')
await goto('/cases/VS-SEG-202', 3200)
const emptySubmit = await evaluate(`
  (() => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '제출')
    return { found: Boolean(btn), disabled: btn ? btn.disabled : null }
  })()
`)
check(emptySubmit.found, '제출 버튼이 있다')
check(emptySubmit.disabled === true, '**입력이 없으면 제출이 막혀 있다** (헛수고를 막는다)')
await shoot('e06-empty-submit')

// ------------------------------------------------------------ 결과
console.log('')
// 401/403 은 이 검증이 **일부러 만드는** 상황이라 제외한다.
// (무효 토큰 · 권한 없는 운영자 화면 접근을 확인하는 것이 목적이다.)
// 그 외의 콘솔 에러는 진짜 문제다.
const realErrors = errorsBefore.filter((e) => !/401|403|Unauthorized|Forbidden/i.test(e))
if (realErrors.length) {
  console.log('콘솔 에러 (의도한 401/403 제외):')
  realErrors.forEach((e) => console.log('  ' + e))
} else {
  console.log('콘솔 에러 없음 (401/403 은 이 검증이 일부러 만드는 상황이라 제외)')
}
writeFileSync(join(OUT, 'result.json'), JSON.stringify({ failures, errors: realErrors }, null, 2))
console.log(failures.length ? `실패 ${failures.length}건: ${failures.join(', ')}` : '전체 통과')
process.exit(failures.length ? 1 : 0)
