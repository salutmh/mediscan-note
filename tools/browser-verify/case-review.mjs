/**
 * 케이스 후보 기술 검수 화면 검증 (v0.8).
 *
 * 여기서 확인하는 것 — **셋 다 무너지면 안 되는 것들이다**:
 *
 *   1) 검수 시트가 실제로 화면에 뜨는가 (인증 뒤에 있는 이미지라 blob 으로 받아야 한다)
 *   2) PASS/HOLD/REJECT 판단이 저장되고 **새로고침해도 남는가**
 *   3) TECH_PASS 를 눌러도 **전문가 검수와 활성화 상태가 바뀌지 않는가**
 *
 * 3번이 이 화면의 핵심이다. 기술 검수가 활성화로 번지면 검수되지 않은 GT 가
 * 학습자의 채점 기준이 된다.
 *
 * 운영자 계정이 필요하다. **자동 승격은 하지 않는다** — 웹으로 스스로 운영자가 되는
 * 경로를 만들지 않는다는 규칙 때문이다. 호출하는 쪽에서 미리 만들어 넘긴다:
 *
 *   python -m scripts.grant_admin --email <이메일>
 *
 * 사용: node case-review.mjs <출력폴더> <디버깅포트> <운영자이메일> [비밀번호]
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
  console.log('운영자 이메일이 필요합니다: node case-review.mjs <출력폴더> <포트> <이메일> [비밀번호]')
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
const goto = async (path, settle = 2500) => {
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

// ------------------------------------------------------------ 0) 운영자 로그인
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
      user_id: d.user_id, email: d.email, nickname: d.nickname,
    }))
    return 'ok'
  })()
`)
if (loggedIn !== 'ok') {
  console.log(`로그인 실패 — ${loggedIn}`)
  process.exit(1)
}

// ------------------------------------------------------------ 1) 목록·시트
console.log('1) 후보 목록과 검수 시트')
await goto('/admin/review', 5000)

const listed = await evaluate(`
  (() => {
    const cards = [...document.querySelectorAll('.case-card')]
    const imgs = cards.map((c) => c.querySelector('.sheet img')).filter(Boolean)
    const loaded = imgs.filter((i) => i.naturalWidth > 0)
    const first = cards[0]
    return {
      cards: cards.length,
      images: imgs.length,
      loadedImages: loaded.length,
      firstText: first ? first.innerText.replace(/\\s+/g, ' ').slice(0, 500) : '',
      notice: document.querySelector('.banner') ? document.querySelector('.banner').textContent.trim() : '',
      statuses: first ? [...first.querySelectorAll('.status-pill')].map((s) => s.textContent.trim()) : [],
      firstCase: first ? first.dataset.case : null,
    }
  })()
`)
check(listed.cards >= 20, '후보 카드가 그려진다', `${listed.cards}개`)
check(
  listed.images > 0 && listed.loadedImages === listed.images,
  '검수 시트 이미지가 실제로 로드된다',
  `${listed.loadedImages}/${listed.images}`,
)
check(
  /기술 검수/.test(listed.notice) && /의학적으로 옳다거나/.test(listed.notice),
  '"기술 검수 ≠ 의학적 검수" 문구가 보인다',
)
check(listed.statuses.length === 3, '세 상태를 항상 함께 보여준다', listed.statuses.join(' | '))
check(/GT voxel/.test(listed.firstText) && /편측/.test(listed.firstText), '계산된 객관값이 보인다')
check(/난이도가 아닙니다/.test(listed.firstText), '크기 구간이 난이도가 아님을 밝힌다')
await shoot('r01-list')

const firstCase = listed.firstCase

// ------------------------------------------------------------ 2) 판단 저장
console.log('2) PASS 저장 — 전문가·활성화 상태는 그대로여야 한다')
await evaluate(`
  (() => {
    const card = document.querySelector('.case-card')
    const btn = [...card.querySelectorAll('button')].find((b) => b.textContent.includes('TECH PASS'))
    if (btn) btn.click()
    return Boolean(btn)
  })()
`)
await sleep(1800)

const afterPass = await evaluate(`
  (() => {
    const card = document.querySelector('.case-card')
    return {
      badge: card.querySelector('.badge').textContent.trim(),
      pills: [...card.querySelectorAll('.status-pill')].map((s) => s.textContent.trim()),
    }
  })()
`)
check(afterPass.badge === 'TECH PASS', 'PASS 가 화면에 반영된다', afterPass.badge)
check(
  afterPass.pills.some((p) => /전문가 검수 대기/.test(p)),
  '**PASS 해도 전문가 검수는 대기 그대로다**',
  afterPass.pills.join(' | '),
)
check(
  afterPass.pills.some((p) => /후보/.test(p) && /미등록/.test(p)),
  '**PASS 해도 활성화되지 않는다**',
  afterPass.pills.join(' | '),
)

// 화면만 바뀐 것이 아닌지 서버에 직접 물어본다
const stored = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/admin/review/candidates/' + ${JSON.stringify(firstCase)}, {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
    })
    const d = await res.json()
    return d.review
  })()
`)
check(stored.technical_review_status === 'tech_pass', '서버에 저장됐다')
check(stored.expert_review_status === 'pending', '서버에서도 전문가 검수는 pending')
check(stored.activation_status === 'candidate', '서버에서도 활성화되지 않았다')

// 새로고침 없이도 상단 현황이 따라가야 한다.
// (처음 만들었을 때 서버 스냅샷을 그대로 써서 "24건 중 24건 미검수"가 계속 보였다 —
//  검수 중 진행률을 보는 것이 헤더의 존재 이유인데 그게 멈춰 있었다.)
const liveCounts = await evaluate(`
  (() => {
    const stats = [...document.querySelectorAll('.progress .stat')].map((s) => [
      s.querySelector('.k').textContent.trim(),
      Number(s.querySelector('.n').textContent),
    ])
    return Object.fromEntries(stats)
  })()
`)
check(liveCounts['TECH PASS'] === 1, '새로고침 없이 헤더가 즉시 갱신된다', JSON.stringify(liveCounts))
check(liveCounts['미검수'] === 23, '미검수 수도 함께 줄어든다', String(liveCounts['미검수']))

await shoot('r02-after-pass')

// ------------------------------------------------------------ 3) 새로고침 유지
console.log('3) 새로고침해도 판단이 남는가')
await goto('/admin/review', 5000)
const afterReload = await evaluate(`
  (() => {
    const card = [...document.querySelectorAll('.case-card')]
      .find((c) => c.dataset.case === ${JSON.stringify(firstCase)})
    return card ? card.querySelector('.badge').textContent.trim() : null
  })()
`)
check(afterReload === 'TECH PASS', '새로 열어도 이전 판단이 유지된다', String(afterReload))

// ------------------------------------------------------------ 4) 현황·필터
console.log('4) 진행 현황과 필터')
const progress = await evaluate(`
  (() => {
    const stats = [...document.querySelectorAll('.progress .stat')].map((s) => ({
      k: s.querySelector('.k').textContent.trim(),
      n: Number(s.querySelector('.n').textContent),
    }))
    return {
      stats,
      filters: [...document.querySelectorAll('.segmented button')].map((b) => b.textContent.trim()),
    }
  })()
`)
const byKey = Object.fromEntries(progress.stats.map((s) => [s.k, s.n]))
check(byKey['전체'] >= 20, '전체 수가 보인다', String(byKey['전체']))
check(byKey['TECH PASS'] >= 1, 'PASS 수가 반영된다', String(byKey['TECH PASS']))
check(byKey['전문가 검수 대기'] >= 1, '전문가 검수 대기 수가 따로 보인다', String(byKey['전문가 검수 대기']))
check(progress.filters.length === 5, '필터 5종이 있다', progress.filters.join(' / '))

await evaluate(`
  (() => {
    const b = [...document.querySelectorAll('.segmented button')].find((x) => x.textContent.trim().startsWith('PASS'))
    if (b) b.click()
    return Boolean(b)
  })()
`)
await sleep(800)
const filteredCount = await evaluate(`document.querySelectorAll('.case-card').length`)
check(filteredCount === byKey['TECH PASS'], 'PASS 필터가 동작한다', `${filteredCount}개`)
await shoot('r03-filter-pass')

// ------------------------------------------------------------ 5) 단축키
console.log('5) 키보드 단축키')
await goto('/admin/review', 5000)
await evaluate(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))`)
await sleep(600)
const focusedIndex = await evaluate(`
  (() => {
    const cards = [...document.querySelectorAll('.case-card')]
    const f = document.querySelector('.case-card.focused')
    return f ? cards.indexOf(f) : -1
  })()
`)
check(focusedIndex === 1, '→ 키로 다음 카드로 이동한다', `index=${focusedIndex}`)

await evaluate(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'h', bubbles: true }))`)
await sleep(1500)
const holdBadge = await evaluate(`
  (() => {
    const cards = [...document.querySelectorAll('.case-card')]
    return cards[1] ? cards[1].querySelector('.badge').textContent.trim() : null
  })()
`)
check(holdBadge === 'HOLD', 'H 키로 HOLD 를 남긴다', String(holdBadge))
await shoot('r04-keyboard')

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
