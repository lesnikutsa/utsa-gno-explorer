const compareText = (left, right) => left < right ? -1 : left > right ? 1 : 0

export const hasValidatorMoniker = (validator) => (
  typeof validator?.moniker === 'string' && validator.moniker.trim().length > 0
)

export const getValidatorPrimaryIdentity = (validator) => (
  hasValidatorMoniker(validator) ? validator.moniker : validator.address
)

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
