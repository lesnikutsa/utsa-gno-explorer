const NON_NEGATIVE_INTEGER = /^\d+$/

export function parseGas(value) {
  if (typeof value !== 'string' || !NON_NEGATIVE_INTEGER.test(value)) return null

  try {
    return BigInt(value)
  } catch {
    return null
  }
}

export function formatGas(value) {
  if (parseGas(value) === null) return '—'
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

export function formatGasUtilization(gasUsed, gasWanted) {
  const used = parseGas(gasUsed)
  const wanted = parseGas(gasWanted)
  if (used === null || wanted === null || wanted === 0n) return '—'

  const scaledNumerator = used * 10_000n
  const quotient = scaledNumerator / wanted
  const remainder = scaledNumerator % wanted
  const roundedHundredths = quotient + (remainder * 2n >= wanted ? 1n : 0n)
  const whole = roundedHundredths / 100n
  const fraction = String(roundedHundredths % 100n).padStart(2, '0').replace(/0+$/, '')
  return `${whole}${fraction ? `.${fraction}` : ''}%`
}
