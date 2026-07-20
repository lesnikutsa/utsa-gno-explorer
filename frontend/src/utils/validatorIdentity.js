const compareText = (left, right) => left < right ? -1 : left > right ? 1 : 0

export const hasValidatorMoniker = (validator) => (
  typeof validator?.moniker === 'string' && validator.moniker.trim().length > 0
)

export const matchesValidatorSearch = (validator, query) => {
  const normalizedQuery = String(query ?? '').trim().toLowerCase()
  if (!normalizedQuery) return true

  const monikerMatches = hasValidatorMoniker(validator)
    && validator.moniker.toLowerCase().includes(normalizedQuery)
  const addressMatches = typeof validator?.address === 'string'
    && validator.address.toLowerCase().includes(normalizedQuery)

  return monikerMatches || addressMatches
}

export const compareValidatorIdentity = (left, right) => {
  const leftHasMoniker = hasValidatorMoniker(left)
  const rightHasMoniker = hasValidatorMoniker(right)

  if (leftHasMoniker && rightHasMoniker) {
    const monikerComparison = compareText(left.moniker.toLowerCase(), right.moniker.toLowerCase())
    if (monikerComparison !== 0) return monikerComparison
  } else if (leftHasMoniker !== rightHasMoniker) {
    return leftHasMoniker ? -1 : 1
  }

  return compareText(left.address, right.address)
}
