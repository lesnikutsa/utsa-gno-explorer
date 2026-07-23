export const TELEGRAM_BOT_USERNAME = 'UTSAGNOBot'
export const TELEGRAM_WATCH_PREFIX = 'watch_topaz_'

const SIGNING_ADDRESS_PATTERN = /^g1[0-9a-z]{38}$/

export function buildTelegramValidatorWatchUrl(signingAddress) {
  if (typeof signingAddress !== 'string') return null

  const normalizedSigningAddress = signingAddress.trim().toLowerCase()
  if (!SIGNING_ADDRESS_PATTERN.test(normalizedSigningAddress)) return null

  const startPayload = `${TELEGRAM_WATCH_PREFIX}${normalizedSigningAddress}`
  return `https://t.me/${TELEGRAM_BOT_USERNAME}?start=${encodeURIComponent(startPayload)}`
}
