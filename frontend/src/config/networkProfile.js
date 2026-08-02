const publicValue = (value, fallback) => (
  typeof value === 'string' && value.trim() ? value.trim() : fallback
)

const links = Object.freeze({
  website: publicValue(import.meta.env.VITE_PROJECT_WEBSITE, 'https://gno.land'),
  documentation: publicValue(import.meta.env.VITE_PROJECT_DOCUMENTATION, 'https://docs.gno.land'),
  github: publicValue(import.meta.env.VITE_PROJECT_GITHUB, 'https://github.com/gnolang/gno'),
})

export const networkProfile = Object.freeze({
  projectName: publicValue(import.meta.env.VITE_PROJECT_NAME, 'Gno.land'),
  networkName: publicValue(import.meta.env.VITE_NETWORK_NAME, 'Topaz'),
  networkIconSrc: publicValue(
    import.meta.env.VITE_NETWORK_ICON,
    '/assets/networks/gnoland.png',
  ),
  nativeDenom: publicValue(
    import.meta.env.VITE_NATIVE_DENOM,
    'ugnot',
  ),
  description: publicValue(
    import.meta.env.VITE_PROJECT_DESCRIPTION,
    'Gno.land is a smart-contract platform built around interpreted Go and transparent on-chain applications. Topaz is the current public test network tracked by UTSA Explorer.',
  ),
  links,
})

export default networkProfile
