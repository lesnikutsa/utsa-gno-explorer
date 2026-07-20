const API_ROOT = import.meta.env.VITE_API_ROOT || '/api'

async function request(path) {
  let response
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      headers: { Accept: 'application/json' },
    })
  } catch (cause) {
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
export const getBlocks = ({ limit, beforeHeight, hash } = {}) => {
  const query = new URLSearchParams()
  if (limit !== undefined && limit !== null && limit !== '') query.set('limit', limit)
  if (beforeHeight !== undefined && beforeHeight !== null && beforeHeight !== '') query.set('before_height', beforeHeight)
  if (hash !== undefined && hash !== null && hash !== '') query.set('hash', hash)
  const queryString = query.toString()
  return request(`/blocks${queryString ? `?${queryString}` : ''}`)
}
export const getBlock = (height) => request(`/blocks/${encodeURIComponent(height)}`)
export const getValidators = () => request('/validators')
export const getValidator = (address) => request(`/validators/${encodeURIComponent(address)}`)

export const getValidatorSigningHistory = ({ limit = 100 } = {}) => {
  const query = new URLSearchParams()
  query.set('limit', limit)
  return request(`/validators/signing-history?${query.toString()}`)
}
