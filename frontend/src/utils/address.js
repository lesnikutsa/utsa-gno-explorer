export const shortAddress = (value) => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '—'
