const SIGNING_ADDRESS_PATTERN = /^g1[0-9a-z]{38}$/
const WATCH_PREFIX_PATTERN = /^[a-z][a-z0-9_]{0,62}_$/

export function buildConfiguredTelegramValidatorWatchUrl({
  botUsername,
  enabled,
  watchPrefix,
  signingAddress,
}) {
  if (enabled !== true) return null
  if (typeof watchPrefix !== 'string') return null

  const normalizedWatchPrefix = watchPrefix.trim().toLowerCase()
  if (!WATCH_PREFIX_PATTERN.test(normalizedWatchPrefix)) return null
  if (typeof signingAddress !== 'string') return null

  const normalizedSigningAddress = signingAddress.trim().toLowerCase()
  if (!SIGNING_ADDRESS_PATTERN.test(normalizedSigningAddress)) return null

  const startPayload = `${normalizedWatchPrefix}${normalizedSigningAddress}`
  return `https://t.me/${botUsername}?start=${encodeURIComponent(startPayload)}`
}
