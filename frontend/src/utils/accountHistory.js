export const emptyAccountHistory = () => ({
  items: [], pagination: null, loading: true,
  initialError: false, pageError: false, pageIndex: 0, canLoadOlder: false,
})

export function historyRequestIsCurrent({ controller, generation, currentGeneration, address, currentAddress }) {
  return !controller.signal.aborted && generation === currentGeneration && address === currentAddress
}
