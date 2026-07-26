const HEIGHT_PATTERN = /^[1-9]\d*$/
const HEX_HASH_PATTERN = /^(?:0[xX])?[0-9a-fA-F]{64}$/
const BASE64_HASH_PATTERN = /^[A-Za-z0-9+/]{43}=$/

export const isPositiveBlockHeight = (query) => HEIGHT_PATTERN.test(query.trim())
export const isExactHexBlockHash = (query) => HEX_HASH_PATTERN.test(query.trim())
export const isExactTransactionHash = (query) => HEX_HASH_PATTERN.test(query.trim())
export const isExactBase64BlockHash = (query) => BASE64_HASH_PATTERN.test(query.trim())
export const isExactBlockHash = (query) => isExactHexBlockHash(query) || isExactBase64BlockHash(query)

export const isValidTransactionHashLookupResponse = (response) => (
  Number.isInteger(response?.block_height)
  && response.block_height > 0
  && Number.isInteger(response?.index)
  && response.index >= 0
  && /^[0-9a-fA-F]{64}$/.test(response?.tx_hash ?? '')
)

export const isValidBlockHashLookupResponse = (response) => (
  Array.isArray(response?.items)
  && response.items.length <= 1
  && response.items.every((block) => Number.isInteger(block?.height) && block.height > 0)
)

export const shouldSearchValidators = (query) => {
  const trimmed = query.trim()
  return trimmed.length >= 2 && !isPositiveBlockHeight(trimmed) && !isExactBlockHash(trimmed)
}

export function findUniqueExactValidatorMatch(query, results) {
  const normalized = query.trim().toLocaleLowerCase()
  if (!normalized) return null
  const signingMatch = results.find((item) => item.address?.toLocaleLowerCase() === normalized)
  if (signingMatch) return signingMatch
  const operatorMatch = results.find((item) => item.operator_address?.toLocaleLowerCase() === normalized)
  if (operatorMatch) return operatorMatch
  const monikerMatches = results.filter((item) => item.moniker?.trim().toLocaleLowerCase() === normalized)
  return monikerMatches.length === 1 ? monikerMatches[0] : null
}

export function chooseValidatorResult(query, results, highlightedIndex = -1) {
  if (highlightedIndex >= 0 && highlightedIndex < results.length) return results[highlightedIndex]
  return findUniqueExactValidatorMatch(query, results) || (results.length === 1 ? results[0] : null)
}
