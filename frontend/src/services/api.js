const API_ROOT = import.meta.env.VITE_API_ROOT || '/api'

async function request(path) {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw new Error(`API request failed with status ${response.status}`)
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
export const getValidators = () => request('/validators')
