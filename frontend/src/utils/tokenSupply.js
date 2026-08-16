export const formatTokenSupply = (value) => {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return '—'
  const [whole, fraction] = value.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return fraction ? `${grouped}.${fraction.replace(/0+$/, '')}`.replace(/\.$/, '') : grouped
}
