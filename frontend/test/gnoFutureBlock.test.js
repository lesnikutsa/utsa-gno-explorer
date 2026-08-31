import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const root = resolve(import.meta.dirname, '..')
const hook = readFileSync(resolve(root, 'src/hooks/useBlockDetail.js'), 'utf8')
const detail = readFileSync(resolve(root, 'src/pages/BlockDetail.jsx'), 'utf8')
const card = readFileSync(resolve(root, 'src/components/FutureBlockCard.jsx'), 'utf8')
const api = readFileSync(resolve(root, 'src/services/api.js'), 'utf8')
const styles = readFileSync(resolve(root, 'src/styles/app.css'), 'utf8')

test('Gno performs live lookup only after an indexed-block 404', () => {
  assert.match(api, /lookupBlock.*\/blocks\/\$\{encodeURIComponent\(height\)\}\/lookup/)
  assert.ok(hook.indexOf('getBlock(height)') < hook.indexOf('lookupBlock(height)'))
  assert.match(hook, /error\.status === 404/)
  assert.match(hook, /lookup\.state !== 'future'/)
})

test('Gno future height uses the shared complete future card', () => {
  assert.match(detail, /lookup\?\.state === 'future'/)
  for (const text of ['has not been produced yet', 'Days', 'Hours', 'Minutes', 'Seconds',
    'Current height', 'Blocks remaining', 'Average block time', 'Estimated arrival',
    'Estimate based on recent network block production.', 'Estimated arrival is temporarily unavailable.']) {
    assert.match(card, new RegExp(text))
  }
})

test('future countdown ticks locally without API polling and remains responsive', () => {
  assert.match(detail, /setInterval\(\(\) => setNow\(Date\.now\(\)\), 1000\)/)
  assert.equal((detail.match(/lookupBlock/g) || []).length, 0)
  assert.match(styles, /repeat\(4, minmax\(0, 1fr\)\)/)
  assert.match(styles, /max-width: 800px[^}]*repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /white-space: nowrap/)
})

test('normal Gno detail contract remains present', () => {
  for (const text of ['Block Information', 'Block Hashes', 'Commit Summary', 'Transactions']) {
    assert.match(detail, new RegExp(text))
  }
})
