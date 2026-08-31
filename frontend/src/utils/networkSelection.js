export const networkIdForPath = (pathname, getNetworkById, defaultNetworkId) => {
  if (typeof pathname !== 'string') return defaultNetworkId
  const match = pathname.match(/^\/networks\/([^/]+)(?:\/|$)/)
  return match && getNetworkById(match[1])?.family === 'cosmos' ? match[1] : defaultNetworkId
}
