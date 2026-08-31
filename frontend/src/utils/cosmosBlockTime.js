export function deriveBlockTimeMetrics(blocks) {
  if (!Array.isArray(blocks)) return { average: undefined, intervals: [], sampleSize: 0 }
  const ordered = [...blocks].sort((left, right) => Number(left.height) - Number(right.height))
  const intervals = []
  for (let index = 1; index < ordered.length; index += 1) {
    if (BigInt(ordered[index].height) !== BigInt(ordered[index - 1].height) + 1n) continue
    const seconds = (Date.parse(ordered[index].timestamp) - Date.parse(ordered[index - 1].timestamp)) / 1000
    if (Number.isFinite(seconds) && seconds > 0 && seconds <= 3600) intervals.push(seconds)
  }
  return {
    average: intervals.length ? intervals.reduce((sum, value) => sum + value, 0) / intervals.length : undefined,
    intervals: intervals.slice(-9),
    sampleSize: intervals.length + (intervals.length ? 1 : 0),
  }
}
