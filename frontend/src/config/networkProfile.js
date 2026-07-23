const publicValue = (value, fallback) => {
  const trimmed = typeof value === 'string' ? value.trim() : ''
  return trimmed || fallback
}

const env = import.meta.env

export const networkProfile = Object.freeze({
  projectName: publicValue(env.VITE_PROJECT_NAME, 'Gno.land'),
  networkName: publicValue(env.VITE_NETWORK_NAME, 'Topaz'),
  description: publicValue(env.VITE_PROJECT_DESCRIPTION, 'Gno.land is a smart-contract platform built around interpreted Go and transparent on-chain applications. Topaz is the current public test network tracked by UTSA Explorer.'),
  links: Object.freeze({
    website: publicValue(env.VITE_PROJECT_WEBSITE, 'https://gno.land'),
    documentation: publicValue(env.VITE_PROJECT_DOCUMENTATION, 'https://docs.gno.land'),
    github: publicValue(env.VITE_PROJECT_GITHUB, 'https://github.com/gnolang/gno'),
  }),
})

export default networkProfile
