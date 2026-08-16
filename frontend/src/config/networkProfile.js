const publicValue = (value, fallback) => (
  typeof value === 'string' && value.trim() ? value.trim() : fallback
)

const publicFlag = (value) => (
  typeof value === 'string' && value.trim().toLowerCase() === 'true'
)

const links = Object.freeze({
  website: publicValue(import.meta.env.VITE_PROJECT_WEBSITE, 'https://gno.land'),
  documentation: publicValue(import.meta.env.VITE_PROJECT_DOCUMENTATION, 'https://docs.gno.land'),
  github: publicValue(import.meta.env.VITE_PROJECT_GITHUB, 'https://github.com/gnolang/gno'),
})

export const networkProfile = Object.freeze({
  projectName: publicValue(import.meta.env.VITE_PROJECT_NAME, 'Gno.land'),
  networkName: publicValue(import.meta.env.VITE_NETWORK_NAME, 'Sapphire'),
  networkIconSrc: publicValue(
    import.meta.env.VITE_NETWORK_ICON,
    '/assets/networks/gnoland.png',
  ),
  nativeDenom: publicValue(
    import.meta.env.VITE_NATIVE_DENOM,
    'ugnot',
  ),
  nativeToken: {
    name: 'GNOT',
    symbol: 'GNOT',
    type: 'Native',
    baseDenom: publicValue(import.meta.env.VITE_NATIVE_DENOM, 'ugnot'),
    decimals: 6,
  },
  description: publicValue(
    import.meta.env.VITE_PROJECT_DESCRIPTION,
    'Gno.land is a smart-contract platform built around interpreted Go and transparent on-chain applications. Sapphire is the current public test network tracked by UTSA Explorer.',
  ),
  telegramValidatorMonitorEnabled: publicFlag(
    import.meta.env.VITE_TELEGRAM_VALIDATOR_MONITOR_ENABLED,
  ),
  telegramValidatorWatchPrefix: publicValue(
    import.meta.env.VITE_TELEGRAM_VALIDATOR_WATCH_PREFIX,
    '',
  ),
  links,
})

export default networkProfile
