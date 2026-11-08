/**
 * Wait until the dev server actually answers, then open the calibrator.
 *
 * Vite binds its port before the dependency optimiser finishes, so opening a
 * browser up front lands on a connection-refused page. Polling the port is what
 * makes "run it and the calibrator appears" work on a cold start.
 */

import { spawn } from 'node:child_process'

const DEFAULT_PATH = '/calibrate'

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function answering(host, port) {
  try {
    const response = await fetch(`http://${host}:${port}/`, {
      signal: AbortSignal.timeout(1000),
    })
    return response.status > 0
  } catch {
    return false
  }
}

function openBrowser(url) {
  const [command, args] =
    process.platform === 'darwin'
      ? ['open', [url]]
      : process.platform === 'win32'
        ? ['cmd', ['/c', 'start', '', url]]
        : ['xdg-open', [url]]
  spawn(command, args, { stdio: 'ignore', detached: true }).unref()
}

export async function openWhenReady(port, options = {}) {
  const path = options.path ?? process.env.AIRTRACK_OPEN_PATH ?? DEFAULT_PATH
  const timeoutMs = options.timeoutMs ?? 180000
  const url = `http://localhost:${port}${path}`
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    // localhost may resolve to ::1 while the server only bound IPv4, or the
    // other way round; accept either before deciding it is not up yet.
    if ((await answering('localhost', port)) || (await answering('127.0.0.1', port))) {
      console.log(`\n  AirTrack is up — opening ${url}\n`)
      if (process.env.AIRTRACK_NO_OPEN !== '1') openBrowser(url)
      return true
    }
    await delay(1000)
  }

  console.log(`\n  Gave up waiting for port ${port}. Open ${url} once the server is up.\n`)
  return false
}

// `node scripts/open-when-ready.mjs 8780` — useful when the server runs elsewhere.
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.argv[2] ?? process.env.DEEPSPACE_PORT ?? 8780)
  await openWhenReady(port)
}
