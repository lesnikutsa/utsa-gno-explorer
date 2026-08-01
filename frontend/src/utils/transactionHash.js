export function shortTransactionHash(value, fallback) {
  return value ? `${value.slice(0, 16)}…${value.slice(-12)}` : fallback
}
