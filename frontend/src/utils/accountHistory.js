export const emptyAccountHistory = () => ({
  items: [], pagination: null, loading: true, loadingMore: false,
  initialError: false, loadMoreError: false,
})

export function mergeAccountHistoryItems(existing, incoming) {
  const merged = new Map(existing.map((item) => [`${item.block_height}:${item.index}`, item]))
  for (const item of incoming) {
    const key = `${item.block_height}:${item.index}`
    if (!merged.has(key)) merged.set(key, item)
  }
  return [...merged.values()]
}

export function historyRequestIsCurrent({ controller, generation, currentGeneration, address, currentAddress }) {
  return !controller.signal.aborted && generation === currentGeneration && address === currentAddress
}
