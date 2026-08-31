const decimalProductRounded = (decimal, integer) => {
  if (typeof decimal !== 'string' || !/^\d+(?:\.\d+)?$/.test(decimal) || !Number.isInteger(integer)) return null
  const [whole, fraction = ''] = decimal.split('.')
  const scale = 10n ** BigInt(fraction.length)
  const product = BigInt(`${whole}${fraction}`) * BigInt(integer)
  return Number((product + scale / 2n) / scale)
}

export function cosmosLivenessRisk({ missedBlocks, startHeight, currentHeight, signedWindow, minimumSigned, averageBlockSeconds }) {
  const minimumSignedBlocks = decimalProductRounded(minimumSigned, signedWindow)
  if (![missedBlocks, startHeight, currentHeight, signedWindow, minimumSignedBlocks].every(Number.isInteger)) return null
  const maxMissed = signedWindow - minimumSignedBlocks
  const budgetLeft = Math.max(0, maxMissed - missedBlocks)
  const thresholdBlocks = Math.max(0, startHeight + signedWindow + 1 - currentHeight)
  const missesToCross = Math.max(0, maxMissed - missedBlocks + 1)
  const earliestBlocks = Math.max(thresholdBlocks, missesToCross)
  const overThreshold = currentHeight > startHeight + signedWindow && missedBlocks > maxMissed
  const usage = maxMissed > 0 ? missedBlocks / maxMissed : missedBlocks > 0 ? 1 : 0
  const tone = overThreshold || usage >= 0.9 ? 'danger'
    : usage >= 0.75 ? 'warning-high'
      : usage >= 0.5 ? 'warning-low' : 'healthy'
  const seconds = Number.isFinite(averageBlockSeconds) && averageBlockSeconds > 0 ? earliestBlocks * averageBlockSeconds : null
  return { minimumSignedBlocks, maxMissed, budgetLeft, earliestBlocks, seconds, overThreshold, tone, usage: Math.min(1, usage) }
}

export function formatApproximateDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const minutes = Math.ceil(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const remaining = minutes % 60
  return hours ? `≈${hours}h ${remaining}m` : `≈${minutes}m`
}
