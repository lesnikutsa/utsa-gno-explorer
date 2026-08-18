import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { transactionTypeVariant } from '../src/components/transactionTypeVariant.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const styles = read('../src/styles/app.css')
const theme = read('../src/styles/theme.css')
const transactions = read('../src/pages/Transactions.jsx')
const accountDetail = read('../src/pages/AccountDetail.jsx')

test('transaction labels map to semantic variants with a neutral fallback', () => {
  assert.equal(transactionTypeVariant('Contract Call'), 'contract-call')
  for (const label of ['NFT Mint', 'NFT Transfer', 'NFT Approval', 'NFT Burn']) {
    assert.equal(transactionTypeVariant(label), 'nft')
  }
  for (const label of ['GRC20 Transfer', 'GRC20 Approval']) {
    assert.equal(transactionTypeVariant(label), 'grc20')
  }
  assert.equal(transactionTypeVariant('Coin Transfer'), 'coin-transfer')
  assert.equal(transactionTypeVariant('Deployment'), 'deployment')
  assert.equal(transactionTypeVariant('Package Run'), 'package-run')
  assert.equal(transactionTypeVariant('Future Transaction'), 'other')
  assert.equal(transactionTypeVariant(undefined), 'other')
})

test('each transaction type variant has centralized badge styling', () => {
  for (const variant of ['contract-call', 'nft', 'grc20', 'coin-transfer', 'deployment', 'package-run', 'other']) {
    assert.match(styles, new RegExp(`\\.transaction-type-badge--${variant} \\{[^}]+\\}`))
  }
})

test('dark and light themes define every transaction type palette token', () => {
  const lightTheme = theme.slice(theme.indexOf(':root[data-theme="light"]'))
  const darkTheme = theme.slice(0, theme.indexOf(':root[data-theme="light"]'))
  for (const token of ['realm', 'package', 'package-deep', 'token', 'neutral', 'nft', 'grc20']) {
    for (const role of ['border', 'background', 'text']) {
      const declaration = `--color-type-${token}-${role}:`
      assert.ok(darkTheme.includes(declaration), `dark theme must define ${declaration}`)
      assert.ok(lightTheme.includes(declaration), `light theme must define ${declaration}`)
    }
  }
})

test('NFT burn uses the NFT palette rather than execution error red', () => {
  assert.equal(transactionTypeVariant('NFT Burn'), 'nft')
  assert.match(styles, /\.transaction-type-badge--nft \{[^}]*color: var\(--color-type-nft-text\)/)
  assert.doesNotMatch(styles, /\.transaction-type-badge--nft \{[^}]*color-error/)
})

test('coin and GRC20 transfers use distinct non-error palettes', () => {
  assert.notEqual(transactionTypeVariant('Coin Transfer'), transactionTypeVariant('GRC20 Transfer'))
  assert.match(styles, /\.transaction-type-badge--grc20 \{[^}]*color: var\(--color-type-grc20-text\)/)
  assert.match(styles, /\.transaction-type-badge--coin-transfer \{[^}]*color: var\(--color-type-package-text\)/)
  assert.doesNotMatch(styles, /\.transaction-type-badge--(?:grc20|coin-transfer) \{[^}]*color-error/)
})

test('transaction views share TransactionTypeBadge mapping', () => {
  const importStatement = "import { TransactionTypeBadge } from '../components/TransactionTypeBadge'"
  assert.ok(transactions.includes(importStatement))
  assert.ok(accountDetail.includes(importStatement))
  assert.match(transactions, /<TransactionTypeBadge[^>]*>\{transaction\.operation\}<\/TransactionTypeBadge>/)
  assert.match(accountDetail, /<TransactionTypeBadge>\{item\.operation\}<\/TransactionTypeBadge>/)
  assert.doesNotMatch(transactions, /transactionTypeVariant/)
  assert.doesNotMatch(accountDetail, /transactionTypeVariant/)
})
