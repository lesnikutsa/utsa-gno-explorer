export const normalizePublicCosmosNetwork = (value) => {
  if (!value || value.family !== 'cosmos' || typeof value.id !== 'string'
      || typeof value.chain_id !== 'string' || typeof value.display_name !== 'string'
      || typeof value.network_name !== 'string' || typeof value.logo_url !== 'string'
      || !value.logo_url.startsWith('https://') || !Array.isArray(value.assets)
      || !value.assets.length || !Array.isArray(value.capabilities)) return null
  const assets = value.assets.map((asset) => Object.freeze({
    base: asset.base, display: asset.display, symbol: asset.symbol, exponent: asset.exponent,
  }))
  if (assets.some((asset) => typeof asset.base !== 'string' || typeof asset.symbol !== 'string'
      || !Number.isInteger(asset.exponent))) return null
  const primary = assets[0]
  return Object.freeze({
    id: value.id, family: 'cosmos', expectedChainId: value.chain_id,
    presentation: Object.freeze({ projectName: value.display_name, networkName: value.network_name,
      networkIconSrc: value.logo_url, nativeDenom: primary.base,
      nativeToken: Object.freeze({ name: primary.symbol, symbol: primary.symbol, type: 'Native',
        baseDenom: primary.base, decimals: primary.exponent }),
      description: `${value.display_name} ${value.network_name} explorer`,
      telegramValidatorMonitorEnabled: false, links: Object.freeze({}) }),
    assets: Object.freeze(assets), addressPrefixes: Object.freeze(value.address_prefixes || {}),
    capabilities: Object.freeze(value.capabilities),
  })
}
