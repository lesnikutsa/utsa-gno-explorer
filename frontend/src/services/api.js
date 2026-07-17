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
export const getBlocks = () => request('/blocks')
export const getValidators = () => request('/validators')
