const publicValue = (value, fallback) => (
  typeof value === 'string' && value.trim() ? value.trim() : fallback
)

const publicFlag = (value) => (
  typeof value === 'string' && value.trim().toLowerCase() === 'true'
)

export const NetworkFamily = Object.freeze({
  GNO: 'gno',
  COSMOS: 'cosmos',
})

export const NetworkCapability = Object.freeze({
  OVERVIEW: 'overview',
  BLOCKS: 'blocks',
  TRANSACTIONS: 'transactions',
  REALMS: 'realms',
  TOKENS: 'tokens',
  VALIDATORS: 'validators',
  GOVERNANCE: 'governance',
  NETWORK_DISTRIBUTION: 'network-distribution',
  VALIDATOR_SIGNING_HISTORY: 'validator-signing-history',
  TELEGRAM_MONITORING: 'telegram-monitoring',
  NETWORK_PARAMETERS: 'network-parameters',
  CONSENSUS_DIAGNOSTICS: 'consensus-diagnostics',
})

const pearlPresentation = Object.freeze({
  projectName: publicValue(import.meta.env.VITE_PROJECT_NAME, 'Gno.land'),
  networkName: publicValue(import.meta.env.VITE_NETWORK_NAME, 'Pearl'),
  networkIconSrc: publicValue(import.meta.env.VITE_NETWORK_ICON, '/assets/networks/gnoland.png'),
  nativeDenom: publicValue(import.meta.env.VITE_NATIVE_DENOM, 'ugnot'),
  nativeToken: Object.freeze({
    name: 'GNOT',
    symbol: 'GNOT',
    type: 'Native',
    baseDenom: publicValue(import.meta.env.VITE_NATIVE_DENOM, 'ugnot'),
    decimals: 6,
  }),
  description: publicValue(
    import.meta.env.VITE_PROJECT_DESCRIPTION,
    'Gno.land is a smart-contract platform built around interpreted Go and transparent on-chain applications. Pearl is the current public test network tracked by UTSA Explorer.',
  ),
  telegramValidatorMonitorEnabled: publicFlag(import.meta.env.VITE_TELEGRAM_VALIDATOR_MONITOR_ENABLED),
  telegramValidatorWatchPrefix: publicValue(import.meta.env.VITE_TELEGRAM_VALIDATOR_WATCH_PREFIX, ''),
  links: Object.freeze({
    website: publicValue(import.meta.env.VITE_PROJECT_WEBSITE, 'https://gno.land'),
    documentation: publicValue(import.meta.env.VITE_PROJECT_DOCUMENTATION, 'https://docs.gno.land'),
    github: publicValue(import.meta.env.VITE_PROJECT_GITHUB, 'https://github.com/gnolang/gno'),
  }),
})

export const supportedNetworks = Object.freeze([
  Object.freeze({
    id: 'gno-pearl',
    family: NetworkFamily.GNO,
    expectedChainId: 'pearl-1',
    presentation: pearlPresentation,
    capabilities: Object.freeze([
      NetworkCapability.OVERVIEW,
      NetworkCapability.BLOCKS,
      NetworkCapability.TRANSACTIONS,
      NetworkCapability.REALMS,
      NetworkCapability.TOKENS,
      NetworkCapability.VALIDATORS,
      NetworkCapability.GOVERNANCE,
      NetworkCapability.NETWORK_DISTRIBUTION,
      NetworkCapability.VALIDATOR_SIGNING_HISTORY,
      NetworkCapability.TELEGRAM_MONITORING,
    ]),
  }),
])

export const DEFAULT_NETWORK_ID = 'gno-pearl'

export const getNetworkById = (networkId) => (
  supportedNetworks.find(({ id }) => id === networkId) ?? null
)

export const hasNetworkCapability = (network, capability) => (
  network.capabilities.includes(capability)
)
