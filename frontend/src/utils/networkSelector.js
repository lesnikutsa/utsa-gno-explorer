export const adjacentOptionIndex = (currentIndex, optionCount, direction) => {
  if (!Number.isInteger(optionCount) || optionCount <= 0) return -1
  const step = direction === 'previous' ? -1 : 1
  const normalizedIndex = Number.isInteger(currentIndex) && currentIndex >= 0 && currentIndex < optionCount
    ? currentIndex
    : step > 0 ? -1 : 0
  return (normalizedIndex + step + optionCount) % optionCount
}
