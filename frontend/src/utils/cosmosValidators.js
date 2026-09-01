import { compareIntegerStrings } from './validatorHealth.js'

export function favoriteFirst(rows, favorites, compare) {
  return [...rows].sort((left, right) => Number(favorites.has(right.operator_address)) - Number(favorites.has(left.operator_address)) || compare(left, right))
}

export function compareNullableIntegerStrings(left, right) {
  if (left == null || right == null) return left == null && right == null ? 0 : left == null ? 1 : -1
  return compareIntegerStrings(left, right)
}

export function compareCosmosValidators(left, right, field) {
  if (field === 'tokens') return compareIntegerStrings(left.tokens, right.tokens)
  if (field === 'change_24h') return compareNullableIntegerStrings(left.change_24h, right.change_24h)
  if (field === 'commission') return Number(left.commission) - Number(right.commission)
  if (field === 'missed_blocks') return Number(left.liveness?.missed_blocks ?? left.missed_blocks ?? 0) - Number(right.liveness?.missed_blocks ?? right.missed_blocks ?? 0)
  if (field === 'moniker') return left.moniker.localeCompare(right.moniker, undefined, { sensitivity: 'base' })
  return 0
}

export function directedValidatorComparison(left, right, field, direction) {
  const comparison = compareCosmosValidators(left, right, field)
  if (field === 'change_24h' && (left.change_24h == null || right.change_24h == null)) return comparison
  return comparison * direction
}

export const missedCountClass = (missed) => `validator-missed-count${missed > 10 ? ' validator-missed-count--alert' : ''}`
