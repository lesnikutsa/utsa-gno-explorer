const DECIMAL_PATTERN = /^-?\d+(?:\.\d+)?$/

export function formatProtocolPercent(value, digits = 2) {
  if (typeof value !== 'string' || !DECIMAL_PATTERN.test(value)) return '—'
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [whole, fraction = ''] = unsigned.split('.')
  const raw = BigInt(`${whole}${fraction}` || '0')
  const divisor = 10n ** BigInt(fraction.length)
  const scaled = raw * 100n * (10n ** BigInt(digits))
  const magnitude = (scaled + divisor / 2n) / divisor
  const rounded = magnitude * (negative ? -1n : 1n)
  const absolute = (rounded < 0n ? -rounded : rounded).toString().padStart(digits + 1, '0')
  return `${rounded < 0n ? '-' : ''}${absolute.slice(0, -digits)}.${absolute.slice(-digits)}%`
}

export function formatProtocolDuration(value) {
  const match = typeof value === 'string' && value.match(/^(\d+)s$/)
  if (!match) return value || '—'
  const seconds = BigInt(match[1])
  const units = [[86400n, 'day'], [3600n, 'hour'], [60n, 'minute']]
  for (const [size, label] of units) {
    if (seconds % size === 0n) {
      const count = seconds / size
      return `${count} ${label}${count === 1n ? '' : 's'}`
    }
  }
  return `${seconds} seconds`
}

export function formatTokenAmount(value, exponent = 6, symbol = '') {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value) || !Number.isInteger(exponent)) return '—'
  const scale = 10n ** BigInt(exponent)
  const units = [[1_000_000_000n, 'B'], [1_000_000n, 'M'], [1_000n, 'K']]
  const [whole, fractional = ''] = value.split('.')
  const precision = fractional.length
  const base = BigInt(`${whole}${fractional}`)
  const decimalScale = 10n ** BigInt(precision)
  for (const [unit, suffix] of units) {
    if (base >= scale * unit * decimalScale) {
      const divisor = scale * unit * decimalScale
      const hundredths = (base * 100n + divisor / 2n) / divisor
      return `${hundredths / 100n}.${(hundredths % 100n).toString().padStart(2, '0')}${suffix}${symbol ? ` ${symbol}` : ''}`
    }
  }
  const divisor = scale * decimalScale
  const displayWhole = base / divisor
  const displayFraction = ((base % divisor) * 1_000_000n / divisor).toString().padStart(6, '0').replace(/0+$/, '')
  return `${displayWhole}${displayFraction ? `.${displayFraction}` : ''}${symbol ? ` ${symbol}` : ''}`
}

export function formatCompactDecimal(value, { prefix = '', suffix = '', digits = 2 } = {}) {
  if (typeof value !== 'string' || !DECIMAL_PATTERN.test(value)) return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  const absolute = Math.abs(number)
  const unit = absolute >= 1e9 ? [1e9, 'B'] : absolute >= 1e6 ? [1e6, 'M'] : absolute >= 1e3 ? [1e3, 'K'] : [1, '']
  const scaled = number / unit[0]
  return `${prefix}${scaled.toFixed(unit[1] ? digits : Math.min(6, digits)).replace(/\.0+$|(?<=\.[0-9]*?)0+$/g, '')}${unit[1]}${suffix}`
}
