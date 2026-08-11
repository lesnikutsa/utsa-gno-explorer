import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { isValidArgumentValue } from '../src/utils/transactionArguments.js'
import { isCanonicalRealmPath, realmDetailHref } from '../src/utils/realm.js'

const summary = readFileSync(new URL('../src/components/TransactionSummary.jsx', import.meta.url), 'utf8')
const detail = readFileSync(new URL('../src/pages/TransactionDetail.jsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

test('message rows use independent native disclosures with only the first open initially', () => {
  assert.match(summary, /const \[open, setOpen\] = useState\(index === 0\)/)
  assert.match(summary, /open=\{open\}/)
  assert.match(summary, /onToggle=\{\(event\) => setOpen\(event\.currentTarget\.open\)\}/)
  assert.match(summary, /function MessageDisclosure/)
  assert.match(summary, /<summary id=/)
  assert.doesNotMatch(summary, /accordion/i)
  assert.match(styles, /transaction-summary__message > summary:focus-visible/)
})

test('each message disclosure owns state that survives parent rerenders independently', () => {
  assert.match(summary, /<MessageDisclosure[\s\S]*key=\{index\}/)
  assert.doesNotMatch(summary, /open=\{index === 0\}/)
  assert.doesNotMatch(summary, /setOpenMessage|activeMessage|openIndex/)
})

test('bounded arguments render as escaped message-local text with fallback and truncation notice', () => {
  assert.match(summary, /argumentDetails\.get\(index\)/)
  assert.match(summary, /detail\.values\.map/)
  assert.match(summary, /value === '' \? '—' : <RealmPathLink path=\{value\} \/>/)
  assert.match(summary, /showArgumentFallback=\{!argumentDetail\}/)
  assert.match(summary, /Some argument values were shortened or are not shown\./)
  assert.doesNotMatch(summary, /dangerouslySetInnerHTML/)
  assert.match(styles, /overflow-wrap: anywhere/)
})

test('canonical realm and package paths use internal detail links without replacing disclosures', () => {
  assert.equal(isCanonicalRealmPath('gno.land/r/gnops/valopers'), true)
  assert.equal(isCanonicalRealmPath('gno.land/p/nt/avl/v0'), true)
  assert.equal(realmDetailHref('gno.land/r/gnops/valopers'), '/realm?path=gno.land%2Fr%2Fgnops%2Fvalopers')
  assert.match(summary, /function RealmPathLink/)
  assert.match(summary, /href=\{realmDetailHref\(path\)\}/)
  assert.match(summary, /<details[\s\S]*<summary id=/)
  assert.match(summary, /stopDisclosureToggle \? \(event\) => event\.stopPropagation\(\)/)
})

test('package details and exact canonical arguments are selectively linked', () => {
  assert.match(summary, /key === 'package_path'[\s\S]*<RealmPathLink path=\{message\[key\]\}/)
  assert.match(summary, /<RealmPathLink path=\{value\} \/>/)
  assert.equal(isCanonicalRealmPath('gno.land/r/gnoland/wugnot'), true)
  assert.equal(isCanonicalRealmPath('gno.land/p/nt/avl/v0'), true)

  for (const value of [
    'g1arw7msrsupe436spp4knv3pnp0n3gn4vjeksmt',
    'hello gno.land/r/foo',
    'https://example.com/gno.land/r/foo',
    'gno.land/x/foo',
    'gno.land/r/foo?bar=1',
    ' gno.land/r/foo',
    'gno.land/r/foo ',
    'gno.land/r/',
    '<a href="/realm">gno.land/r/foo</a>',
  ]) assert.equal(isCanonicalRealmPath(value), false, value)

  assert.doesNotMatch(summary, /dangerouslySetInnerHTML/)
})

test('realm links retain monospace wrapping and keyboard focus styling', () => {
  assert.match(styles, /\.transaction-summary__realm-link \{[^}]*font-family: var\(--font-mono\)[^}]*overflow-wrap: anywhere/)
  assert.match(styles, /\.transaction-summary__realm-link:focus-visible/)
})

test('four-field sender details are prioritized while three-field MsgSend is not', () => {
  assert.match(summary, /const hasCrowdedSender = fields\.length >= 4\s*&& fields\.some\(\(\{ key \}\) => key === 'sender'\)/)
  assert.match(summary, /hasCrowdedSender \? ' transaction-summary__details--sender-priority' : ''/)
  assert.match(summary, /key === 'sender' \? ' transaction-summary__detail--sender' : ''/)
  assert.doesNotMatch(summary, /key === 'recipient' \? ' transaction-summary__detail--sender'/)

  const hasCrowdedSender = (keys) => keys.length >= 4 && keys.includes('sender')
  assert.equal(hasCrowdedSender(['sender', 'send', 'package_path', 'function']), true)
  assert.equal(hasCrowdedSender(['sender', 'recipient', 'amount']), false)
  assert.equal(hasCrowdedSender(['recipient', 'send', 'package_path', 'function']), false)
})

test('crowded sender layout preserves the default grid and uses a scoped responsive override', () => {
  assert.match(styles, /\.transaction-summary__details \{ display: grid; grid-template-columns: repeat\(auto-fit, minmax\(240px, 1fr\)\); margin: 0; border-top: 1px solid var\(--color-border-soft\); \}/)
  assert.match(styles, /\.transaction-summary__details--sender-priority \{ grid-template-columns: minmax\(300px, 1\.25fr\) repeat\(auto-fit, minmax\(210px, 1fr\)\); \}/)
  assert.match(styles, /@media \(max-width: 800px\) \{\s*\.transaction-summary__details--sender-priority \{ grid-template-columns: 1fr; \}\s*\}/)
  assert.doesNotMatch(styles, /@media \(max-width: 700px\) \{\s*\.transaction-summary__details--sender-priority/)

  const scopedRules = `${summary}\n${styles.match(/\.transaction-summary__details--sender-priority[^}]*\}/g)?.join('\n')}`
  assert.doesNotMatch(scopedRules, /text-overflow|ellipsis|font-size|overflow-x|white-space:\s*nowrap/)
})

test('argument limits count Unicode code points and reject controls', () => {
  assert.equal(isValidArgumentValue('a'.repeat(256)), true)
  assert.equal(isValidArgumentValue('🙂'.repeat(256)), true)
  assert.equal(isValidArgumentValue('🙂'.repeat(257)), false)
  assert.equal(isValidArgumentValue('control\nvalue'), false)
  assert.equal(isValidArgumentValue(''), true)
})

test('Developer Data keeps raw Base64 behind a nested disclosure', () => {
  assert.match(detail, /<summary>Developer Data<\/summary>/)
  assert.match(detail, /<summary>Show raw transaction<\/summary>/)
  assert.doesNotMatch(detail, /transaction-detail__developer-actions/)
  assert.doesNotMatch(styles, /transaction-detail__developer-actions/)
  const rawDisclosure = detail.slice(detail.indexOf('<summary>Show raw transaction</summary>'))
  const rawContent = rawDisclosure.slice(rawDisclosure.indexOf('transaction-detail__raw-content'))
  assert.match(rawContent, /<div className="panel__heading"><h2>Raw Transaction Base64<\/h2><CopyButton value=\{transaction\.raw_base64\} label="raw transaction" \/><\/div>/)
  assert.match(rawContent, /<pre className="transaction-detail__raw-value mono">\{transaction\.raw_base64\}<\/pre>/)
  assert.ok(rawContent.indexOf('label="raw transaction"') < rawContent.indexOf('transaction-detail__raw-value'))
  assert.doesNotMatch(detail, /Technical Data|Encoded length|Low-level encoded transaction data/)
  assert.match(detail, /Execution Details/)
})

test('transaction hash copy control stays beside the wrapping heading hash', () => {
  assert.match(detail, /<div className="transaction-detail__copy-row transaction-detail__copy-row--heading">\s*<h1 className="transaction-detail__heading-hash mono"[^>]*>\{transaction\.tx_hash\}<\/h1>\s*<CopyButton value=\{transaction\.tx_hash\} label="transaction hash" \/>/)
  assert.match(styles, /\.transaction-detail__heading-hash \{ flex: 0 1 auto;/)
  assert.match(styles, /\.transaction-detail__copy-row--heading \{ width: fit-content; max-width: 100%; \}/)
  assert.match(styles, /\.transaction-detail__copy-row--heading \.copy-button \{ flex: 0 0 auto; \}/)
  assert.match(styles, /\.transaction-detail__copy-row \{ display: flex; align-items: flex-start; gap: 8px; min-width: 0; \}/)
  assert.match(styles, /\.transaction-detail__hash \{ flex: 1 1 auto;/)
})
