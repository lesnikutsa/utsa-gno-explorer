import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const validatorsPage = readFileSync(new URL('../src/pages/Validators.jsx', import.meta.url), 'utf8')
const telegramConfig = readFileSync(new URL('../src/utils/telegram.js', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

test('Telegram monitoring URL uses the shared bot username without a start payload', () => {
  assert.match(telegramConfig, /export const TELEGRAM_BOT_USERNAME = 'UTSAGNOBot'/)
  assert.match(telegramConfig, /export const TELEGRAM_BOT_URL = `https:\/\/t\.me\/\$\{TELEGRAM_BOT_USERNAME\}`/)
  assert.doesNotMatch(telegramConfig, /TELEGRAM_BOT_URL[^\n]*[?&]start=/)
})

test('Validators page exposes Telegram Monitoring as a safe accessible external link', () => {
  assert.match(validatorsPage, /href=\{TELEGRAM_BOT_URL\}/)
  assert.match(validatorsPage, /target="_blank"/)
  assert.match(validatorsPage, /rel="noopener noreferrer"/)
  assert.match(validatorsPage, /aria-label="Open Telegram Monitoring \(opens in a new tab\)"/)
  assert.match(validatorsPage, />\s*Telegram Monitoring\s*<\/a>/)
})

test('Validators page keeps the manual Refresh control', () => {
  assert.match(validatorsPage, /onClick=\{refresh\}/)
  assert.match(validatorsPage, /\{manualRefreshing \? 'Refreshing…' : 'Refresh'\}/)
})

test('Telegram Monitoring has dedicated theme-aware interaction styling', () => {
  assert.match(validatorsPage, /className="blocks-page__button blocks-page__button--telegram"/)
  assert.match(styles, /\.blocks-page__button--telegram \{/)
  assert.match(styles, /\.blocks-page__button--telegram:hover:not\(:disabled\) \{/)
  assert.match(styles, /\.blocks-page__button--telegram:focus-visible \{/)
  assert.match(styles, /:root\[data-theme="light"\] \.blocks-page__button--telegram \{/)
})
