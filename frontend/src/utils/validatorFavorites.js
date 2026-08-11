export const VALIDATOR_FAVORITES_KEY_PREFIX = 'utsa-gno-explorer.validator-favorites.v1:'

const storageKey = (chainId) => `${VALIDATOR_FAVORITES_KEY_PREFIX}${chainId}`

const resolveStorage = (storage) => {
  if (storage !== undefined) return storage

  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

export function loadValidatorFavorites(chainId, storage) {
  if (!chainId) return new Set()

  try {
    const value = JSON.parse(resolveStorage(storage)?.getItem(storageKey(chainId)) ?? '[]')
    if (!Array.isArray(value) || value.some((address) => typeof address !== 'string')) return new Set()
    return new Set(value)
  } catch {
    return new Set()
  }
}

export function saveValidatorFavorites(chainId, favorites, storage) {
  if (!chainId) return

  try {
    resolveStorage(storage)?.setItem(storageKey(chainId), JSON.stringify([...favorites]))
  } catch {
    // Storage can be unavailable in privacy-restricted browsing contexts.
  }
}

export function toggleValidatorFavorite(favorites, address) {
  const nextFavorites = new Set(favorites)
  if (nextFavorites.has(address)) nextFavorites.delete(address)
  else nextFavorites.add(address)
  return nextFavorites
}

export function compareFavoriteGroups(left, right, favorites) {
  return Number(favorites.has(right.address)) - Number(favorites.has(left.address))
}
