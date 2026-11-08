#!/usr/bin/env node
/**
 * One command that does what "Run" should do: boot the DeepSpace dev server
 * and open the calibrator as soon as the port answers.
 *
 *   npm run dev:open            # 8780, then /calibrate
 *   npm run dev:open -- --port 5173
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { openWhenReady } from './open-when-ready.mjs'

const argv = process.argv.slice(2)
const portFlag = argv.indexOf('--port')
const port = Number(portFlag >= 0 ? argv[portFlag + 1] : (process.env.DEEPSPACE_PORT ?? 8780))

const isWindows = process.platform === 'win32'
const localBin = join(process.cwd(), 'node_modules', '.bin', isWindows ? 'deepspace.cmd' : 'deepspace')
const [command, args] = existsSync(localBin)
  ? [localBin, ['dev', 'start', '--port', String(port)]]
  : ['npx', ['deepspace', 'dev', 'start', '--port', String(port)]]

console.log(`\n  starting: ${command} ${args.join(' ')}\n`)
const child = spawn(command, args, { stdio: 'inherit' })

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal))
}

openWhenReady(port).catch(() => {})

child.on('exit', (code, signal) => {
  process.exit(code ?? (signal ? 0 : 1))
})
