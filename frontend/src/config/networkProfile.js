import { DEFAULT_NETWORK_ID, getNetworkById } from './networkRegistry'

// Compatibility export for presentation-only consumers. Static identity and
// capabilities live on the registry entry, while runtime chain identity does not.
export const networkProfile = getNetworkById(DEFAULT_NETWORK_ID).presentation

export default networkProfile
