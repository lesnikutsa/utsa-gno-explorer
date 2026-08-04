import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealmCalls } from '../services/api'
import { idleRealmCallsState, loadingRealmCallsState, selectRealmCallsStateForPath } from '../utils/realmDetail'

export const REALM_CALLS_PAGE_SIZE = 25
const callKey = (item) => `${item.block_height}:${item.tx_index}:${item.message_index}`
const hasCursor = (pagination) => pagination?.next_before_height != null && pagination?.next_before_tx_index != null && pagination?.next_before_message_index != null


export function useRealmCalls(path) {
  const [state, setState] = useState(() => path ? loadingRealmCallsState(path) : idleRealmCallsState(null))
  const activeRef = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)
  const effectiveState = selectRealmCallsStateForPath(state, path)

  const load = useCallback((cursor = null) => {
    if (!path || activeRef.current) return
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    const requestedPath = path
    const older = cursor !== null
    activeRef.current = true
    if (older) {
      setState((current) => {
        const selected = selectRealmCallsStateForPath(current, requestedPath)
        return { ...selected, path: requestedPath, loadingOlder: true, olderError: false }
      })
    } else {
      setState(loadingRealmCallsState(requestedPath))
    }
    getRealmCalls({
      path: requestedPath,
      limit: REALM_CALLS_PAGE_SIZE,
      beforeHeight: cursor?.height,
      beforeTxIndex: cursor?.txIndex,
      beforeMessageIndex: cursor?.messageIndex,
      signal: activeController.signal,
    }).then((response) => {
      if (id !== requestId.current || activeController.signal.aborted) return
      const rows = (response.items ?? []).slice(0, REALM_CALLS_PAGE_SIZE)
      setState((current) => {
        const selected = selectRealmCallsStateForPath(current, requestedPath)
        const seen = new Set(selected.items.map(callKey))
        const items = older
          ? [...selected.items, ...rows.filter((row) => !seen.has(callKey(row)))]
          : rows
        return { path: requestedPath, items, pagination: response.pagination ?? null, loading: false, loadingOlder: false, error: false, olderError: false, unavailable: false }
      })
    }).catch((requestError) => {
      if (id !== requestId.current || requestError?.name === 'AbortError') return
      setState((current) => {
        const selected = selectRealmCallsStateForPath(current, requestedPath)
        if (requestError?.status === 409) return { ...selected, path: requestedPath, loading: false, loadingOlder: false, unavailable: true }
        if (older) return { ...selected, path: requestedPath, loadingOlder: false, olderError: true }
        return { ...selected, path: requestedPath, loading: false, loadingOlder: false, error: true }
      })
    }).finally(() => {
      if (id !== requestId.current) return
      activeRef.current = false
    })
  }, [path])

  const retry = useCallback(() => load(null), [load])
  const loadOlder = useCallback(() => {
    if (activeRef.current || !hasCursor(effectiveState.pagination)) return
    load({ height: effectiveState.pagination.next_before_height, txIndex: effectiveState.pagination.next_before_tx_index, messageIndex: effectiveState.pagination.next_before_message_index })
  }, [effectiveState.pagination, load])

  useEffect(() => {
    controller.current?.abort()
    requestId.current += 1
    activeRef.current = false
    if (!path) {
      setState(idleRealmCallsState(null))
      return undefined
    }
    load(null)
    return () => {
      requestId.current += 1
      controller.current?.abort()
    }
  }, [load, path])

  return { ...effectiveState, retry, loadOlder, canLoadOlder: hasCursor(effectiveState.pagination) }
}
