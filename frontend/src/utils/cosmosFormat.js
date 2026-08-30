export const isSectionError = (value) => Boolean(value?.error)

export const formatBaseAmount = (amount, exponent = 0, maximumFractionDigits = exponent) => {
  if (!/^(0|[1-9]\d*)$/.test(String(amount)) || !Number.isInteger(exponent) || exponent < 0) return '—'
  const padded = String(amount).padStart(exponent + 1, '0')
  const whole = exponent ? padded.slice(0, -exponent) : padded
  const fraction = exponent ? padded.slice(-exponent).replace(/0+$/, '').slice(0, maximumFractionDigits) : ''
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`
}

export const formatRatio = (value) => {
  if (value === null || value === undefined || !/^(0|[1-9]\d*)(\.\d+)?$/.test(String(value))) return '—'
  const [whole, fraction = ''] = String(value).split('.')
  const scaled = `${whole}${fraction.padEnd(4, '0').slice(0, 4)}`.replace(/^0+(?=\d)/, '')
  const percent = BigInt(scaled || '0') * 100n
  const text = percent.toString().padStart(5, '0')
  return `${text.slice(0, -4)}.${text.slice(-4).replace(/0+$/, '') || '0'}%`
}

export const formatMarketPercent = (value) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`

export const validateCosmosHeight = (value) => {
  const normalized = String(value).trim()
  if (!/^[1-9]\d*$/.test(normalized)) return { error: 'Enter a positive whole-number block height.' }
  if (BigInt(normalized) > BigInt(Number.MAX_SAFE_INTEGER)) return { error: 'This height is outside the supported numeric range.' }
  return { height: normalized }
}

export const mergeBlockWindow = (previous, incoming, maximum = 20) => {
  const rows = Array.isArray(incoming) ? incoming : incoming?.blocks || []
  if (!rows.length) return previous
  const priorHead = BigInt(previous?.[0]?.height || 0)
  const nextHead = BigInt(rows[0]?.height || 0)
  const incomingTail = BigInt(rows.at(-1)?.height || 0)
  const transitionIsCovered = !priorHead || incomingTail <= priorHead + 1n
  const source = transitionIsCovered ? [...rows, ...(previous || [])] : rows
  return [...new Map(source.map((block) => [String(block.height), block])).values()]
    .sort((a, b) => BigInt(a.height) > BigInt(b.height) ? -1 : 1).slice(0, maximum)
}
