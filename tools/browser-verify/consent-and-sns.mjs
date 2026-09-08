/**
 * 화면 0 검증: 동의 체크박스 + SNS 개발용 간편가입 3종 + 이메일 가입.
 *
 * **실제 마우스 클릭**(CDP Input.dispatchMouseEvent)으로 누른다 —
 * el.click() 은 라벨/체크박스의 브라우저 기본 동작을 재현하지 못해서, 화면에서만 나는
 * 버그(전체동의 후 개별 해제 불가 등)를 놓친다.
 *
 * 사용: node consent-and-sns.mjs <출력폴더> <디버깅포트>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9350)
const BASE = 'http://localhost:5173'
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const failures = []
const check = (ok, label) => {
  console.log(`   ${ok ? 'OK ' : 'FAIL'}  ${label}`)
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
const { sessionId } = await cdp.send('Target.attachToTarget', { targetId: page.targetId, flatten: true })
cdp.sessionId = sessionId
await cdp.send('Page.enable')
await cdp.send('Runtime.enable')
await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false })

const errors = []
await cdp.send('Log.enable').catch(() => {})
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.method === 'Log.entryAdded' && m.params?.entry?.level === 'error') {
    const e = m.params.entry
    errors.push(`${e.text} ${e.url ?? ''}`.trim())
  }
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
const goto = async (path, settle = 1500) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}
const shoot = async (name) => {
  const { cssContentSize } = await cdp.send('Page.getLayoutMetrics')
  const { data } = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: cssContentSize.width, height: Math.min(cssContentSize.height, 5000), scale: 1 },
  })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
}

/** 진짜 마우스 클릭 (좌표 기반) */
async function clickAt(x, y) {
  const common = { x, y, button: 'left', clickCount: 1 }
  await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...common })
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...common })
  await sleep(180)
}

/**
 * 셀렉터 중심 좌표.
 * **먼저 화면 안으로 스크롤한다** — 뷰포트 밖 좌표로 마우스 이벤트를 보내면 아무 데도 안 맞고,
 * 그걸 앱 버그로 착각하게 된다 (실제로 이 스크립트를 처음 돌렸을 때 그렇게 잘못 읽혔다).
 */
const centerOf = (selector, index = 0) => evaluate(`
  (() => {
    const el = document.querySelectorAll(${JSON.stringify(selector)})[${index}]
    if (!el) return null
    el.scrollIntoView({ block: 'center', inline: 'center' })
    const r = el.getBoundingClientRect()
    const inView = r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, inView, w: r.width, h: r.height }
  })()
`)

async function clickSelector(selector, index = 0) {
  const point = await centerOf(selector, index)
  if (!point) throw new Error(`요소를 찾지 못함: ${selector}[${index}]`)
  if (!point.inView || point.w === 0 || point.h === 0) {
    throw new Error(`클릭 대상이 화면 밖이거나 크기가 0: ${selector}[${index}] ${JSON.stringify(point)}`)
  }
  await clickAt(point.x, point.y)
}

/** 동의 체크 상태 스냅샷 */
const consentState = () => evaluate(`
  (() => {
    const all = document.querySelector('.consents .row.all input')
    const rows = [...document.querySelectorAll('.consents .row:not(.all)')].map((row) => ({
      key: row.querySelector('.label-text')?.textContent.trim(),
      required: row.querySelector('.tag')?.textContent.trim() === '필수',
      checked: row.querySelector('input').checked,
    }))
    const submit = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '가입 완료')
    return {
      all: !!all?.checked,
      rows,
      progress: document.querySelector('.consents .progress')?.textContent.trim(),
      submitDisabled: submit ? submit.disabled : null,
    }
  })()
`)

const clickText = (text) => evaluate(`
  (() => {
    const el = [...document.querySelectorAll('button, a')].find((b) => b.textContent.trim() === ${JSON.stringify(text)})
    el?.click()
    return !!el
  })()
`)

// ---------------------------------------------------------------- 1) 동의 UI
console.log('1) 회원가입 동의 체크박스 — 실제 마우스 클릭으로 검증')
await goto('/login', 1200)
await evaluate("localStorage.clear(); 'ok'")
await goto('/login', 1800)
await clickText('회원가입')
await sleep(700)

let state = await consentState()
console.log(`   동의 항목 ${state.rows.length}개 (필수 ${state.rows.filter((r) => r.required).length})`)
check(state.rows.length === 6, '동의 항목 6개가 렌더링된다')
check(state.rows.every((r) => !r.checked), '초기 상태는 전부 해제')
check(state.submitDisabled === true, '초기에는 가입 완료 비활성')

// 개별 체크 — 첫 번째 항목
await clickSelector('.consents .row:not(.all) input', 0)
state = await consentState()
check(state.rows[0].checked === true, '개별 항목 1번 체크됨')
check(state.rows.slice(1).every((r) => !r.checked), '다른 항목은 그대로')
check(state.all === false, '일부만 체크 → 전체동의 해제 상태')

// 개별 해제
await clickSelector('.consents .row:not(.all) input', 0)
state = await consentState()
check(state.rows[0].checked === false, '개별 항목 1번 다시 해제됨')

// 라벨 텍스트 클릭으로도 토글되는지 (라벨이 input 을 감싸고 있다)
await clickSelector('.consents .row:not(.all) .label-text', 1)
state = await consentState()
check(state.rows[1].checked === true, '라벨 텍스트 클릭으로도 체크됨')
await clickSelector('.consents .row:not(.all) .label-text', 1)
state = await consentState()
check(state.rows[1].checked === false, '라벨 텍스트 클릭으로 해제됨')

// 전체 동의
await clickSelector('.consents .row.all input')
state = await consentState()
check(state.all === true && state.rows.every((r) => r.checked), '전체동의 → 전부 체크')
check(state.submitDisabled === false, '필수 충족 → 가입 완료 활성')
await shoot('c01-all-checked')

// 전체동의 후 선택 항목만 해제
const optionalIndex = state.rows.findIndex((r) => !r.required)
await clickSelector('.consents .row:not(.all) input', optionalIndex)
state = await consentState()
check(state.rows[optionalIndex].checked === false, '전체동의 후에도 선택 동의 해제 가능')
check(state.all === false, '항목 하나 해제 → 전체동의 자동 해제')
check(state.submitDisabled === false, '선택 동의는 가입 조건이 아니다 (여전히 활성)')
await shoot('c02-optional-unchecked')

// 필수 하나 해제 → 가입 막힘
const requiredIndex = state.rows.findIndex((r) => r.required)
await clickSelector('.consents .row:not(.all) input', requiredIndex)
state = await consentState()
check(state.rows[requiredIndex].checked === false, '필수 항목 해제됨')
check(state.submitDisabled === true, '필수 미충족 → 가입 완료 비활성')

// 전체동의 해제 → 전부 해제
await clickSelector('.consents .row.all input') // 먼저 전체 체크
await sleep(150)
await clickSelector('.consents .row.all input') // 다시 해제
state = await consentState()
check(state.all === false && state.rows.every((r) => !r.checked), '전체동의 해제 → 전부 해제')

// 필수만 체크해서 가입 가능한지
for (let i = 0; i < state.rows.length; i += 1) {
  if (state.rows[i].required) await clickSelector('.consents .row:not(.all) input', i)
}
state = await consentState()
check(state.rows.filter((r) => r.required).every((r) => r.checked), '필수 전부 체크')
check(state.rows.filter((r) => !r.required).every((r) => !r.checked), '선택은 해제 상태 유지')
check(state.submitDisabled === false, '필수만 체크해도 가입 가능')
console.log(`   진행표시: ${state.progress}`)
await shoot('c03-required-only')

// ---------------------------------------------- 2) 이메일 가입 -> 케이스 목록
console.log('2) 이메일 회원가입 → 케이스 목록')
const email = `consent${Date.now()}@example.com`
await evaluate(`
  (() => {
    const set = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })) }
    const inputs = document.querySelectorAll('.field input')
    set(inputs[0], ${JSON.stringify(email)})
    set(inputs[1], 'pw12345678')
    set(inputs[2], '동의테스트')
    return 'filled'
  })()
`)
await sleep(300)
await clickText('가입 완료')
await sleep(2500)
let path = await evaluate('location.pathname')
let cases = await evaluate(`document.querySelectorAll('.case-card').length`)
let ids = await evaluate(`[...document.querySelectorAll('.case-card h3, .case-card .case-id, .case-card strong')].map(e=>e.textContent.trim()).join(',')`)
check(path === '/cases', `이메일 가입 후 케이스 목록 이동 (현재 ${path})`)
check(cases === 6, `VS-SEG 6개 케이스 표시 (현재 ${cases}개)`)
check(!!(await evaluate("localStorage.getItem('mediscan.access_token')")), '이메일 가입: access token 저장')
console.log(`   케이스: ${ids}`)
await shoot('c04-email-cases')

// ------------------------------------------------------- 3) SNS 3종
for (const [provider, label] of [['kakao', '카카오로 시작하기'], ['google', 'Google로 시작하기'], ['naver', '네이버로 시작하기']]) {
  console.log(`3) SNS ${provider}`)
  await goto('/login', 1200)
  await evaluate("localStorage.clear(); 'ok'")
  await goto('/login', 1800)

  const noteVisible = await evaluate(`!!document.querySelector('.social-note')`)
  check(noteVisible, `${provider}: "개발용 예시 로그인" 안내가 보인다`)

  await clickText(label)
  await sleep(1800)

  // 신규 사용자면 동의 화면이 뜬다 -> 전체동의 후 가입
  const needsConsent = await evaluate(`!!document.querySelector('.consents')`)
  if (needsConsent) {
    await clickSelector('.consents .row.all input')
    await sleep(200)
    await clickText('가입 완료')
    await sleep(2500)
  }

  path = await evaluate('location.pathname')
  cases = await evaluate(`document.querySelectorAll('.case-card').length`)
  const token = await evaluate("localStorage.getItem('mediscan.access_token')")
  check(!!token, `${provider}: access token 저장`)
  check(path === '/cases', `${provider}: 케이스 목록 이동 (현재 ${path})`)
  check(cases === 6, `${provider}: VS-SEG 6개 케이스 표시 (현재 ${cases}개)`)
  await shoot(`c05-sns-${provider}`)

  // 같은 provider 로 다시 누르면 기존 계정 로그인 (동의 화면 없이 바로 이동).
  // mock provider_token 은 localStorage 에 저장돼 "같은 SNS 계정" 역할을 하므로 지우지 않는다.
  await goto('/login', 1200)
  await evaluate("localStorage.removeItem('mediscan.access_token'); 'ok'")
  await goto('/login', 1500)
  await clickText(label)
  await sleep(2500)
  path = await evaluate('location.pathname')
  check(path === '/cases', `${provider}: 재로그인 시 동의 없이 바로 이동 (현재 ${path})`)
}

/**
 * SNS 최초 로그인은 consents 없이 먼저 호출해 400(CONSENT_REQUIRED)을 받고 동의 화면으로
 * 넘어간다 (api-spec 1절의 의도된 흐름). 브라우저는 실패한 fetch 를 항상 error 로 찍으므로
 * 여기서 걸러낸다 - 걸러내지 않으면 스크립트가 매번 '실패'로 끝나 신호가 무의미해진다.
 */
const EXPECTED_ERROR = /auth\/social-login/
const unexpected = errors.filter((e) => !EXPECTED_ERROR.test(e))
console.log('')
console.log(`콘솔 에러 ${errors.length}건 (예상된 SNS 동의 400 ${errors.length - unexpected.length}건 제외 -> ${unexpected.length}건)`)
for (const e of unexpected.slice(0, 8)) console.log('  ' + e)
if (unexpected.length) failures.push(`예상 밖 콘솔 에러 ${unexpected.length}건`)

if (failures.length) {
  console.log('\n실패:')
  for (const f of failures) console.log('  - ' + f)
  ws.close()
  process.exit(1)
}
console.log('\n전체 통과')
ws.close()
