import assert from 'node:assert/strict'
import test from 'node:test'

import { buildConfiguredTelegramValidatorWatchUrl } from '../src/utils/telegramWatch.js'

const signingAddress = `g1${'a'.repeat(38)}`
const baseConfig = {
  botUsername: 'UTSAGNOBot',
  enabled: true,
  watchPrefix: 'watch_future_',
  signingAddress,
}

test('enabled monitoring still fails closed without a configured prefix', () => {
  for (const watchPrefix of [undefined, '', '   ']) {
    assert.equal(buildConfiguredTelegramValidatorWatchUrl({ ...baseConfig, watchPrefix }), null)
  }
})

test('an explicitly configured valid future prefix generates a watch URL', () => {
  assert.equal(
    buildConfiguredTelegramValidatorWatchUrl(baseConfig),
    `https://t.me/UTSAGNOBot?start=watch_future_${signingAddress}`,
  )
})

test('disabled monitoring and malformed prefixes fail closed', () => {
  assert.equal(buildConfiguredTelegramValidatorWatchUrl({ ...baseConfig, enabled: false }), null)
  for (const watchPrefix of ['watch-future_', 'https://example.com/?', 'watch_future', '?start=']) {
    assert.equal(buildConfiguredTelegramValidatorWatchUrl({ ...baseConfig, watchPrefix }), null)
  }
})
