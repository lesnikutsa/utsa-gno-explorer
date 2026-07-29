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
