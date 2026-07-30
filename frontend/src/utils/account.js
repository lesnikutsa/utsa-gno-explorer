export const decodeAccountRouteAddress = (routeAddress) => {
  if (typeof routeAddress !== 'string' || routeAddress.length === 0 || routeAddress.length > 128) return null

  try {
    const address = decodeURIComponent(routeAddress)
    if (address.length === 0 || address.length > 128 || address.includes('/')) return null
    return address
  } catch {
    return null
  }
}

export const findNativeBalance = (balances, nativeDenom) => (
  balances.find((balance) => balance.denom === nativeDenom)
)

export const findOtherBalances = (balances, nativeDenom) => (
  balances.filter((balance) => balance.denom !== nativeDenom)
)

export const getAccountDetailView = ({ account, requestedAddress, loading, invalidAddress, unavailable, error }) => {
  if (!account && (!requestedAddress || invalidAddress)) return 'invalid'
  if (!account && unavailable) return 'unavailable'
  if (!account && error) return 'error'
  if (account && !account.found) return 'missing'
  if (!account && loading) return 'loading'
  return 'account'
}

export const formatAmountString = (value) => {
  const text = String(value)
  const [integer, ...fractionParts] = text.split('.')
  const groupedInteger = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return fractionParts.length > 0 ? `${groupedInteger}.${fractionParts.join('.')}` : groupedInteger
}
