/**
 * ROI 되돌리기/다시하기 — **실제 캔버스 픽셀로** 확인한다.
 *
 * 왜 브라우저에서 보는가
 * ---------------------
 * jsdom 에는 canvas 백엔드가 없어서 단위 테스트(`RoiCanvas.test.js`)는
 * 가짜 컨텍스트를 끼워 넣고 **동작 순서**만 본다. 그것으로는
 * "되돌렸더니 그림이 정말 이전 상태로 돌아왔는가"를 증명할 수 없다.
 * 여기서는 칠해진 픽셀 수를 세서 확인한다.
 *
 * 사용: node tools/browser-verify/roi-undo.mjs
 *   (백엔드 :8010, 프론트 :5173, 디버깅 포트 9333 의 헤드리스 Chrome 필요)
 */
const PORT = 9333, BASE = 'http://localhost:5173', API = 'http://localhost:8010/api'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()
const ws = new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r))
let id = 0; const pending = new Map(); let session = null
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } }
const send = (method, params = {}, useSession = true) => new Promise((res, rej) => {
  const msg = { id: ++id, method, params }; if (useSession && session) msg.sessionId = session
  pending.set(msg.id, (m) => (m.error ? rej(new Error(m.error.message)) : res(m.result)))
  ws.send(JSON.stringify(msg)) })
const { targetId } = await send('Target.createTarget', { url: 'about:blank' }, false)
session = (await send('Target.attachToTarget', { targetId, flatten: true }, false)).sessionId
await send('Page.enable'); await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
const evalJs = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + JSON.stringify(r.result?.value)); return r.result.value }
const go = async (p) => { await send('Page.navigate', { url: BASE + p }); await sleep(1800) }

await go('/login')
await evalJs(`(async () => {
  const consents = {agree_terms:true,agree_privacy:true,agree_sensitive_data:true,agree_ai_notice:true,agree_age14:true,agree_marketing:false}
  const r = await fetch('${API}/auth/signup', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email:'undo${Date.now()}@example.com',password:'Passw0rd!23',nickname:'검증',consents})})
  const j = await r.json()
  localStorage.setItem('mediscan.access_token', j.access_token)
  localStorage.setItem('mediscan.user', JSON.stringify({user_id:j.user_id,email:j.email,nickname:j.nickname}))
  return 'ok' })()`)
await go('/cases/VS-SEG-202')

// 마우스로 실제 획 두 개를 그린다
const box = await evalJs(`JSON.stringify(document.querySelector('canvas').getBoundingClientRect())`)
const r = JSON.parse(box)
async function strokeAt(fx, fy) {
  const x = Math.round(r.left + r.width * fx), y = Math.round(r.top + r.height * fy)
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x + 30, y: y + 30, button: 'left' })
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x + 30, y: y + 30, button: 'left', clickCount: 1 })
  await sleep(250)
}
const painted = () => evalJs(`(() => {
  const c = document.querySelector('canvas'); const x = c.getContext('2d')
  const d = x.getImageData(0,0,c.width,c.height).data
  let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++
  return n })()`)

console.log('초기 칠해진 픽셀:', await painted())
await strokeAt(0.35, 0.55); const after1 = await painted(); console.log('획 1 뒤:', after1)
await strokeAt(0.6, 0.6);  const after2 = await painted(); console.log('획 2 뒤:', after2)

const undoBtn = `document.querySelectorAll('.viewer-bar .icon')[0]`
await evalJs(`${undoBtn}.click()`); await sleep(400)
const afterUndo = await painted(); console.log('되돌리기 뒤:', afterUndo)

const redoBtn = `document.querySelectorAll('.viewer-bar .icon')[1]`
await evalJs(`${redoBtn}.click()`); await sleep(400)
const afterRedo = await painted(); console.log('다시하기 뒤:', afterRedo)

const ok = after1 > 0 && after2 > after1 && Math.abs(afterUndo - after1) < after1 * 0.05 && Math.abs(afterRedo - after2) < after2 * 0.05
console.log(ok ? '\n판정: 통과 — 되돌리기/다시하기가 실제 픽셀을 복원한다' : '\n판정: 실패')
// **만든 탭을 닫는다.** 다른 스크립트들은 기존 탭을 재사용하지만 이 스크립트는
// 새로 만든다. 닫지 않으면 반복 실행할수록 헤드리스 Chrome 에 탭이 쌓이고,
// 그 상태에서는 **다른 스크립트의 전체 페이지 스크린샷이 타임아웃난다**
// (실제로 admin-ux / case-review 가 그렇게 멈췄다).
try {
  await send('Target.closeTarget', { targetId }, false)
} catch {
  /* 이미 닫혔으면 그만이다 */
}
ws.close(); process.exit(ok ? 0 : 1)
