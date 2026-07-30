const HEIGHT_PATTERN = /^[1-9]\d*$/
const HEX_HASH_PATTERN = /^(?:0[xX])?[0-9a-fA-F]{64}$/
const BASE64_HASH_PATTERN = /^[A-Za-z0-9+/]{43}=$/
const BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
const BECH32_GENERATORS = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]

function bech32Polymod(values) {
  let checksum = 1
  for (const value of values) {
    const top = checksum >>> 25
    checksum = ((checksum & 0x1ffffff) << 5) ^ value
    for (let index = 0; index < BECH32_GENERATORS.length; index += 1) {
      if ((top >>> index) & 1) checksum ^= BECH32_GENERATORS[index]
    }
  }
  return checksum >>> 0
}

function convertFiveToEightBits(values) {
  let accumulator = 0
  let bits = 0
  const output = []
  for (const value of values) {
    accumulator = (accumulator << 5) | value
    bits += 5
    while (bits >= 8) {
      bits -= 8
      output.push((accumulator >>> bits) & 0xff)
    }
  }
  if (bits >= 5 || ((accumulator << (8 - bits)) & 0xff) !== 0) return null
  return output
}

export function isValidAccountAddress(query) {
  if (typeof query !== 'string') return false
  const address = query.trim()
  if (address.length < 8 || address.length > 90 || address !== address.toLowerCase()) return false
  if ([...address].some((character) => character.charCodeAt(0) < 33 || character.charCodeAt(0) > 126)) return false

  const separator = address.lastIndexOf('1')
  if (separator < 1 || separator + 7 > address.length || address.slice(0, separator) !== 'g') return false
  const values = [...address.slice(separator + 1)].map((character) => BECH32_CHARSET.indexOf(character))
  if (values.some((value) => value < 0)) return false
  const expandedHrp = [address.charCodeAt(0) >>> 5, 0, address.charCodeAt(0) & 31]
  if (bech32Polymod([...expandedHrp, ...values]) !== 1) return false
  const payload = convertFiveToEightBits(values.slice(0, -6))
  return payload !== null && payload.length === 20
}

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
    && !isValidAccountAddress(trimmed)
}

export function resolveAccountAddressDestination(address, results) {
  const normalized = address.trim().toLocaleLowerCase()
  const validator = results.find((item) => (
    item.address?.toLocaleLowerCase() === normalized
    || item.operator_address?.toLocaleLowerCase() === normalized
  ))
  return validator?.address
    ? `/validators/${encodeURIComponent(validator.address)}`
    : `/accounts/${encodeURIComponent(address.trim())}`
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
