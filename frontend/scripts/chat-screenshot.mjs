// Screenshot the chat page in compare mode via headless Chrome (needs the API and `npm run dev` running).
// Usage: node scripts/chat-screenshot.mjs ../docs/screenshots/chat.png
import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const out = process.argv[2]
const question = process.argv[3] ?? 'What share of answers is off-topic for each topic?'
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--remote-debugging-port=9223',
  '--user-data-dir=/tmp/chrome-cdp', '--window-size=1280,1800', 'about:blank',
], { stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

try {
  let targets = []
  for (let i = 0; i < 30 && !targets.length; i++) {
    await sleep(500)
    targets = await fetch('http://127.0.0.1:9223/json').then((r) => r.json(), () => [])
  }
  const page = targets.find((t) => t.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((r) => ws.addEventListener('open', r))
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (e) => {
    const msg = JSON.parse(e.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
    if (msg.method === 'Runtime.exceptionThrown') console.error('page error:', msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text)
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') console.error('page log:', msg.params.entry.text, msg.params.entry.url ?? '')
  })
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result?.result?.value
  const waitFor = async (expression, seconds) => {
    for (let i = 0; i < seconds * 2; i++) {
      if (await evaluate(expression)) return
      await sleep(500)
    }
    const text = await evaluate(`location.href + '\\n' + document.body.innerText.slice(0, 500)`)
    throw new Error(`timed out waiting for: ${expression}\npage: ${text}`)
  }
  const buttons = (test) => `[...document.querySelectorAll('button')].filter(b => ${test})`
  const label = (b) => `${b}.textContent.trim()`

  await send('Runtime.enable')
  await send('Log.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1800, deviceScaleFactor: 1, mobile: false })
  await send('Page.navigate', { url: 'http://localhost:5173/chat' })
  const compare = buttons(`${label('b')} === 'Compare'`)
  await waitFor(`${compare}.length > 0`, 30)
  await evaluate(`${compare}[0].click()`)
  const suggestion = buttons(`${label('b')} === ${JSON.stringify(question)}`)
  await waitFor(`${suggestion}.length > 0`, 10)
  await evaluate(`${suggestion}[0].click()`)
  const traces = buttons(`/^Show (agent )?trace$/.test(${label('b')})`)
  await waitFor(`${traces}.length >= 2`, 180)
  await evaluate(`${traces}.forEach(b => b.click())`)
  await sleep(800)
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(out, Buffer.from(shot.result.data, 'base64'))
  ws.close()
  console.log('saved', out)
} finally {
  chrome.kill()
}
