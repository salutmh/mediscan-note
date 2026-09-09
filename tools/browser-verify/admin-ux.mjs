/**
 * 운영자 화면 UX 검증 (v0.9).
 *
 * 여기서 확인하는 것 — **운영자가 실수로 학습자에게 영향을 주지 않는가**:
 *
 *   1) 검색·필터가 동작하는가 (케이스가 늘면 스크롤로 못 찾는다)
 *   2) 노출/숨김 버튼이 **동작**을 말하는가 (예전엔 "노출 중"이라 상태였다)
 *   3) 숨기기 전에 확인을 거치는가 · 제출 이력 건수를 알려주는가
 *   4) 소견 없이 `검토 완료` 를 **고를 수 없는가**
 *      (예전엔 고를 수 있게 해놓고 서버가 422 로 실패시켰다)
 *   5) 숨긴 케이스가 실제로 학습자 목록에서 사라지는가
 *
 * 운영자 계정이 필요하다:
 *   python -m scripts.grant_admin --email <이메일>
 *
 * 사용: node admin-ux.mjs <출력폴더> <디버깅포트> <운영자이메일> [비밀번호]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9333)
const ADMIN_EMAIL = process.argv[4]
const ADMIN_PASSWORD = process.argv[5] ?? 'pw12345678'
const BASE = 'http://localhost:5173'
const API = 'http://localhost:8010'
mkdirSync(OUT, { recursive: true })

if (!ADMIN_EMAIL) {
  console.log('운영자 이메일이 필요합니다: node admin-ux.mjs <출력폴더> <포트> <이메일> [비밀번호]')
  process.exit(1)
}

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
await cdp.send('Emulation.setDeviceMetricsOverride', {
  width: 1440,
  height: 1000,
  deviceScaleFactor: 1,
  mobile: false,
})

const errors = []
await cdp.send('Log.enable').catch(() => {})
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.method === 'Log.entryAdded' && m.params?.entry?.level === 'error') {
    errors.push(m.params.entry.text)
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
const goto = async (path, settle = 3000) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}
const shoot = async (name) => {
  const { cssContentSize } = await cdp.send('Page.getLayoutMetrics')
  const { data } = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip: {
      x: 0,
      y: 0,
      width: cssContentSize.width,
      height: Math.min(cssContentSize.height, 4000),
      scale: 1,
    },
  })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
}

// ------------------------------------------------------------ 0) 로그인
console.log('0) 운영자 로그인')
await goto('/login')
const loggedIn = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: ${JSON.stringify(ADMIN_EMAIL)},
        password: ${JSON.stringify(ADMIN_PASSWORD)},
      }),
    })
    const d = await res.json()
    if (!d.access_token) return 'FAIL ' + JSON.stringify(d).slice(0, 200)
    localStorage.setItem('mediscan.access_token', d.access_token)
    localStorage.setItem('mediscan.user', JSON.stringify({
      user_id: d.user_id, nickname: d.nickname,
    }))
    return 'ok'
  })()
`)
if (loggedIn !== 'ok') {
  console.log(`로그인 실패 — ${loggedIn}`)
  process.exit(1)
}

await goto('/admin/cases', 4000)

// ------------------------------------------------------ 1) 검색·필터
console.log('1) 검색과 필터')
const toolbar = await evaluate(`
  (() => ({
    hasSearch: Boolean(document.querySelector('.toolbar input[type=search]')),
    filters: [...document.querySelectorAll('.toolbar .segmented button')].map((b) => b.textContent.trim()),
    rows: document.querySelectorAll('.admin-table tbody tr:not(.editor-row)').length,
  }))()
`)
check(toolbar.hasSearch, '케이스 검색이 있다')
check(toolbar.filters.length >= 4, '필터가 있다', toolbar.filters.join(' / '))
const totalRows = toolbar.rows

const searched = await evaluate(`
  (() => {
    const input = document.querySelector('.toolbar input[type=search]')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, '202')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    return 'typed'
  })()
`)
await sleep(600)
const afterSearch = await evaluate(
  `document.querySelectorAll('.admin-table tbody tr:not(.editor-row)').length`,
)
check(afterSearch < totalRows && afterSearch >= 1, '검색이 목록을 좁힌다', `${totalRows} -> ${afterSearch}`)

await evaluate(`
  (() => {
    const input = document.querySelector('.toolbar input[type=search]')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, '')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    return 'cleared'
  })()
`)
await sleep(400)
await shoot('a01-toolbar')

// ------------------------------------------- 2) 버튼이 동작을 말하는가
console.log('2) 노출/숨김 버튼')
const toggle = await evaluate(`
  (() => {
    const row = document.querySelector('.admin-table tbody tr:not(.editor-row)')
    const tag = row.querySelector('.state-tag')
    const buttons = [...row.querySelectorAll('button')].map((b) => b.textContent.trim())
    return { state: tag ? tag.textContent.trim() : null, buttons }
  })()
`)
check(toggle.state === '노출 중', '현재 상태가 따로 표시된다', String(toggle.state))
check(
  toggle.buttons.includes('숨기기'),
  '**버튼이 동작을 말한다** (예전엔 "노출 중"이라 상태였다)',
  toggle.buttons.join(', '),
)

// ------------------------------------------------ 3) 숨기기 확인 단계
console.log('3) 숨기기 확인')
const targetCase = await evaluate(`
  (() => {
    const row = document.querySelector('.admin-table tbody tr:not(.editor-row)')
    const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '숨기기')
    btn.click()
    return row.querySelector('strong').textContent.trim()
  })()
`)
await sleep(700)

const confirming = await evaluate(`
  (() => {
    const row = document.querySelector('.admin-table tbody tr:not(.editor-row)')
    const box = row.querySelector('.confirm')
    return {
      shown: Boolean(box),
      text: box ? box.innerText.replace(/\\s+/g, ' ') : '',
      buttons: box ? [...box.querySelectorAll('button')].map((b) => b.textContent.trim()) : [],
    }
  })()
`)
check(confirming.shown, '한 번에 숨겨지지 않는다 (확인 단계가 있다)')
check(/학습자|복습노트/.test(confirming.text), '무엇이 사라지는지 알려준다', confirming.text.slice(0, 60))
check(/제출/.test(confirming.text), '제출 이력 건수를 함께 보여준다')
check(confirming.buttons.includes('취소'), '되돌릴 수 있다')
await shoot('a02-confirm-hide')

// 취소하면 그대로여야 한다
await evaluate(`
  (() => {
    const btn = [...document.querySelectorAll('.confirm button')].find((b) => b.textContent.trim() === '취소')
    if (btn) btn.click()
    return true
  })()
`)
await sleep(500)
const stillActive = await evaluate(`
  (() => {
    const row = document.querySelector('.admin-table tbody tr:not(.editor-row)')
    return row.querySelector('.state-tag').textContent.trim()
  })()
`)
check(stillActive === '노출 중', '취소하면 아무 일도 일어나지 않는다', stillActive)

// ------------------------------- 4) 고를 수 없는 값을 고를 수 있게 두지 않는가
console.log('4) 소견 없이 "검토 완료"')
const statusOptions = await evaluate(`
  (() => {
    const row = document.querySelector('.admin-table tbody tr:not(.editor-row)')
    const selects = [...row.querySelectorAll('select')]
    const status = selects[selects.length - 1]
    return {
      options: [...status.options].map((o) => ({
        text: o.textContent.trim(), value: o.value, disabled: o.disabled,
      })),
      hint: row.innerText.includes('소견을 먼저 등록'),
    }
  })()
`)
const approved = statusOptions.options.find((o) => o.value === 'approved')
check(
  approved && approved.disabled,
  '**소견이 없으면 "검토 완료" 를 고를 수 없다**',
  approved ? `disabled=${approved.disabled}` : '(항목 없음)',
)
check(approved && /소견 필요/.test(approved.text), '왜 못 고르는지 항목에 적혀 있다', approved?.text)
check(statusOptions.hint, '무엇을 먼저 해야 하는지 알려준다')
await shoot('a03-status-locked')

// ----------------------------- 5) 숨기면 학습자 목록에서 실제로 사라지는가
console.log('5) 숨김이 학습자 화면에 반영되는가')
const learnerBefore = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/cases', {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
    })
    const d = await res.json()
    return (d.cases || []).map((c) => c.case_id)
  })()
`)

await evaluate(`
  (async () => {
    const token = localStorage.getItem('mediscan.access_token')
    await fetch('${API}/api/admin/cases/' + ${JSON.stringify(targetCase)}, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      body: JSON.stringify({ is_active: false }),
    })
    return 'hidden'
  })()
`)
const learnerAfter = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/cases', {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
    })
    const d = await res.json()
    return (d.cases || []).map((c) => c.case_id)
  })()
`)
check(
  learnerBefore.includes(targetCase) && !learnerAfter.includes(targetCase),
  '숨기면 학습자 목록에서 사라진다',
  `${learnerBefore.length} -> ${learnerAfter.length}`,
)

// 되돌린다 (검증이 데이터를 남기지 않게)
await evaluate(`
  (async () => {
    const token = localStorage.getItem('mediscan.access_token')
    await fetch('${API}/api/admin/cases/' + ${JSON.stringify(targetCase)}, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      body: JSON.stringify({ is_active: true }),
    })
    return 'restored'
  })()
`)
const restored = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/cases', {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
    })
    const d = await res.json()
    return (d.cases || []).map((c) => c.case_id).includes(${JSON.stringify(targetCase)})
  })()
`)
check(restored, '다시 노출하면 돌아온다 (검증이 데이터를 남기지 않는다)')

// ------------------------------------------------------------ 결과
console.log('')
if (errors.length) {
  console.log('콘솔 에러:')
  errors.forEach((e) => console.log('  ' + e))
} else {
  console.log('콘솔 에러 없음')
}
writeFileSync(join(OUT, 'result.json'), JSON.stringify({ failures, errors }, null, 2))
console.log(failures.length ? `실패 ${failures.length}건: ${failures.join(', ')}` : '전체 통과')
process.exit(failures.length || errors.length ? 1 : 0)
