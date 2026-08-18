const API_ROOT = import.meta.env?.VITE_API_ROOT || '/api'

export async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      headers: { Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
      method: options.method ?? 'GET',
      body: options.body,
      signal: options.signal,
    })
  } catch (cause) {
    if (cause?.name === 'AbortError' || options.signal?.aborted) throw cause
    const error = new Error('Unable to reach the Explorer API', { cause })
    error.status = 0
    error.detail = 'Network request failed'
    throw error
  }

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : ''
    } catch {
      detail = ''
    }
    const error = new Error(`API request failed with status ${response.status}`)
    error.status = response.status
    error.detail = detail
    throw error
  }

  return response.json()
}

export const getHealth = () => request('/health')
export const getNetwork = () => request('/network')
export const getNetworkDistribution = () => request('/network/distribution')
export const getBlocks = ({ limit, beforeHeight, hash } = {}) => {
  const query = new URLSearchParams()
  if (limit !== undefined && limit !== null && limit !== '') query.set('limit', limit)
  if (beforeHeight !== undefined && beforeHeight !== null && beforeHeight !== '') query.set('before_height', beforeHeight)
  if (hash !== undefined && hash !== null && hash !== '') query.set('hash', hash)
  const queryString = query.toString()
  return request(`/blocks${queryString ? `?${queryString}` : ''}`)
}
export const getTransactions = ({ limit, beforeHeight, beforeTxIndex } = {}) => {
  const query = new URLSearchParams()
  if (limit !== undefined && limit !== null && limit !== '') query.set('limit', limit)
  const hasCompleteCursor = beforeHeight !== undefined && beforeHeight !== null && beforeHeight !== ''
    && beforeTxIndex !== undefined && beforeTxIndex !== null && beforeTxIndex !== ''
  if (hasCompleteCursor) {
    query.set('before_height', beforeHeight)
    query.set('before_tx_index', beforeTxIndex)
  }
  const queryString = query.toString()
  return request(`/transactions${queryString ? `?${queryString}` : ''}`)
}
export const getRealms = ({ limit, kind, q, beforeActivityHeight, beforePath, signal } = {}) => {
  const query = new URLSearchParams()
  if (limit !== undefined && limit !== null && limit !== '') query.set('limit', limit)
  if (kind !== undefined && kind !== null && kind !== '') query.set('kind', kind)
  const trimmedQuery = typeof q === 'string' ? q.trim() : ''
  if (trimmedQuery) query.set('q', trimmedQuery)
  const hasCompleteCursor = beforeActivityHeight !== undefined && beforeActivityHeight !== null && beforeActivityHeight !== ''
    && beforePath !== undefined && beforePath !== null && beforePath !== ''
  if (hasCompleteCursor) {
    query.set('before_activity_height', beforeActivityHeight)
    query.set('before_path', beforePath)
  }
  const queryString = query.toString()
  return request(`/realms${queryString ? `?${queryString}` : ''}`, { signal })
}
export const getTokens = ({ limit = 50, q, activityWindow = '24h', beforeActivityHeight, beforePath, signal } = {}) => {
  const query = new URLSearchParams({ limit })
  query.set('activity_window', activityWindow)
  const trimmedQuery = typeof q === 'string' ? q.trim() : ''
  if (trimmedQuery) query.set('q', trimmedQuery)
  if (beforeActivityHeight !== undefined && beforePath) {
    query.set('before_activity_height', beforeActivityHeight)
    query.set('before_path', beforePath)
  }
  return request(`/tokens?${query.toString()}`, { signal })
}
export const getAssets = ({ limit = 50, q, standard = 'all', beforeActivityHeight, beforePath, signal } = {}) => {
  const query = new URLSearchParams({ limit, standard })
  const trimmedQuery = typeof q === 'string' ? q.trim() : ''
  if (trimmedQuery) query.set('q', trimmedQuery)
  if (beforeActivityHeight !== undefined && beforePath) {
    query.set('before_activity_height', beforeActivityHeight)
    query.set('before_path', beforePath)
  }
  return request(`/assets?${query.toString()}`, { signal })
}
export const getNftActivity = (paths, { signal } = {}) => {
  return request('/assets/nft-activity', { signal, method: 'POST', body: JSON.stringify({ paths }) })
}
export const getTokenSupply = (path, { signal } = {}) => {
  const query = new URLSearchParams({ path })
  return request(`/tokens/supply?${query.toString()}`, { signal })
}
export const getNativeToken = ({ signal } = {}) => request('/tokens/native', { signal })
export const getTopRealmNamespaces = ({ limit = 3, scope = 'curated', signal } = {}) => {
  const query = new URLSearchParams()
  query.set('limit', limit)
  query.set('scope', scope)
  return request(`/realm-namespaces/top?${query.toString()}`, { signal })
}

export const getTopRealmApplications = ({ limit = 3, window = '24h', signal } = {}) => {
  const query = new URLSearchParams()
  query.set('limit', limit)
  query.set('window', window)
  return request(`/realm-applications/top?${query.toString()}`, { signal })
}

export const getBlock = (height) => request(`/blocks/${encodeURIComponent(height)}`)
export const getTransaction = (blockHeight, index) => request(`/blocks/${encodeURIComponent(blockHeight)}/transactions/${encodeURIComponent(index)}`)
export const getTransactionByHash = (txHash) => request(`/transactions/by-hash/${encodeURIComponent(txHash)}`)
export const getValidators = () => request('/validators')
export const searchValidators = ({ query, limit = 6 }) => {
  const params = new URLSearchParams()
  params.set('q', query)
  params.set('limit', limit)
  return request(`/search/validators?${params.toString()}`)
}
export const getValidator = (address) => request(`/validators/${encodeURIComponent(address)}`)
export const getAccount = (address) => request(`/accounts/${encodeURIComponent(address)}`)
export const getAccountTransactions = (address, { limit, beforeHeight, beforeTxIndex, signal } = {}) => {
  const query = new URLSearchParams()
  if (limit !== undefined) query.set('limit', limit)
  if (beforeHeight !== undefined && beforeTxIndex !== undefined) {
    query.set('before_height', beforeHeight)
    query.set('before_tx_index', beforeTxIndex)
  }
  const suffix = query.toString()
  return request(`/accounts/${encodeURIComponent(address)}/transactions${suffix ? `?${suffix}` : ''}`, { signal })
}
export const getGovernanceProposals = ({ limit, beforeProposalId } = {}) => {
  const query = new URLSearchParams()
  if (limit !== undefined && limit !== null && limit !== '') query.set('limit', limit)
  if (beforeProposalId !== undefined && beforeProposalId !== null && beforeProposalId !== '') query.set('before_proposal_id', beforeProposalId)
  const queryString = query.toString()
  return request(`/governance/proposals${queryString ? `?${queryString}` : ''}`)
}
export const getGovernanceProposal = (proposalId) => request(`/governance/proposals/${encodeURIComponent(proposalId)}`)

export const getValidatorSigningHistory = ({ limit = 100 } = {}) => {
  const query = new URLSearchParams()
  query.set('limit', limit)
  return request(`/validators/signing-history?${query.toString()}`)
}
export const getRealmDetail = ({ path, signal } = {}) => {
  const query = new URLSearchParams()
  query.set('path', path)
  return request(`/realms/detail?${query.toString()}`, { signal })
}
export const getRealmMetadata = ({ path, signal } = {}) => {
  const query = new URLSearchParams({ path })
  return request(`/realms/metadata?${query.toString()}`, { signal })
}
export const getRealmMetadataFile = ({ path, filename, signal } = {}) => {
  const query = new URLSearchParams({ path, filename })
  return request(`/realms/metadata/file?${query.toString()}`, { signal })
}
export const getRealmCalls = ({ path, limit = 25, beforeHeight, beforeTxIndex, beforeMessageIndex, signal } = {}) => {
  const query = new URLSearchParams()
  query.set('path', path)
  query.set('limit', limit)
  const hasCompleteCursor = beforeHeight !== undefined && beforeHeight !== null && beforeHeight !== ''
    && beforeTxIndex !== undefined && beforeTxIndex !== null && beforeTxIndex !== ''
    && beforeMessageIndex !== undefined && beforeMessageIndex !== null && beforeMessageIndex !== ''
  if (hasCompleteCursor) {
    query.set('before_height', beforeHeight)
    query.set('before_tx_index', beforeTxIndex)
    query.set('before_message_index', beforeMessageIndex)
  }
  return request(`/realms/calls?${query.toString()}`, { signal })
}
