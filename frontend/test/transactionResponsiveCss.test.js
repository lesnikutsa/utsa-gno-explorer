import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

function mediaBody(maxWidth, occurrence = 0) {
  const marker = `@media (max-width: ${maxWidth}px)`
  let start = -1
  for (let match = 0; match <= occurrence; match += 1) start = styles.indexOf(marker, start + 1)
  assert.notEqual(start, -1, `${marker} must exist`)

  const openingBrace = styles.indexOf('{', start)
  let depth = 1
  for (let index = openingBrace + 1; index < styles.length; index += 1) {
    if (styles[index] === '{') depth += 1
    if (styles[index] === '}') depth -= 1
    if (depth === 0) return styles.slice(openingBrace + 1, index)
  }

  assert.fail(`${marker} must have a closing brace`)
}

test('transaction grid keeps desktop placement and explicitly resets it in responsive cards', () => {
  for (const [child, column] of [[1, 1], [2, 3], [3, 5], [4, 7], [5, 9], [6, 11]]) {
    assert.ok(styles.includes(`.transactions-page__table .data-table tr > :nth-child(${child}) { grid-column: ${column}; }`))
  }

  const responsive = mediaBody(1180)
  assert.match(responsive, /\.transactions-page__table \.data-table \{ width: 100%; min-width: 0; \}/)
  assert.match(responsive, /\.transactions-page__table \.data-table thead \{ display: none; \}/)
  assert.match(responsive, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  for (let child = 1; child <= 6; child += 1) {
    assert.ok(responsive.includes(`.transactions-page__table .data-table tbody tr > :nth-child(${child})`))
  }
  assert.match(responsive, /:nth-child\(6\) \{ grid-column: auto; \}/)
  assert.doesNotMatch(responsive, /overflow-x:\s*(auto|scroll)/)

  assert.match(mediaBody(520), /\.transactions-page__table \.data-table tbody tr \{ grid-template-columns: minmax\(0, 1fr\); \}/)
})

test('account transaction grid keeps desktop placement and explicitly resets it in responsive cards', () => {
  for (const [child, column] of [[1, 1], [2, 3], [3, 5], [4, 7], [5, 9], [6, 11], [7, 13]]) {
    assert.ok(styles.includes(`.account-detail__transaction > :nth-child(${child}) { grid-column: ${column}; }`))
  }

  const responsive = mediaBody(1450)
  assert.match(responsive, /\.account-detail__transaction-header \{ display: none; \}/)
  assert.match(responsive, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  for (let child = 1; child <= 7; child += 1) {
    assert.ok(responsive.includes(`.account-detail__transaction > :nth-child(${child})`))
  }
  assert.match(responsive, /:nth-child\(7\) \{ grid-column: auto; \}/)
  assert.match(responsive, /\.account-detail__transaction-counterparty \{ white-space: normal; overflow-wrap: anywhere; \}/)
  assert.doesNotMatch(responsive, /(?:html|body|page)[^{]*\{[^}]*overflow-x/)

  assert.match(mediaBody(520, 1), /\.account-detail__transaction \{ grid-template-columns: minmax\(0, 1fr\); \}/)
})

test('responsive transaction contracts remain scoped to the two affected views', () => {
  const responsiveRules = `${mediaBody(1180)}\n${mediaBody(1450)}`
  for (const selector of ['blocks-page', 'validators', 'governance', 'overview', 'transaction-detail', 'sidebar']) {
    assert.equal(responsiveRules.includes(selector), false)
  }
  assert.doesNotMatch(styles, /(?:html|body)\s*\{[^}]*overflow-x:\s*(?:auto|scroll)/)
})
