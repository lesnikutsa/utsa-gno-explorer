export const formatTokenSupply = (value) => {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return '—'
  const [whole, fraction] = value.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return fraction ? `${grouped}.${fraction.replace(/0+$/, '')}`.replace(/\.$/, '') : grouped
}

const NARROW_NO_BREAK_SPACE = '\u202f'

const groupNativeSupply = (value) => value.replace(/\B(?=(\d{3})+(?!\d))/g, NARROW_NO_BREAK_SPACE)

export const formatNativeSupply = (value) => {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) {
    return { display: '—', exact: '—' }
  }

  const [whole, fraction = ''] = value.split('.')
  const hasFraction = /[1-9]/.test(fraction)
  const roundsUp = hasFraction && fraction[0] >= '5'
  const roundedWhole = roundsUp ? (BigInt(whole) + 1n).toString() : whole
  const exact = `${groupNativeSupply(whole)}${fraction ? `.${fraction}` : ''}`

  return {
    display: `${hasFraction ? '≈ ' : ''}${groupNativeSupply(roundedWhole)}`,
    exact,
  }
}
