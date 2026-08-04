import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealmCalls } from '../services/api'
import { getRealmCallsNextCursor, idleRealmCallsState, loadingRealmCallsState, selectRealmCallsStateForPath } from '../utils/realmDetail'

export const REALM_CALLS_PAGE_SIZE = 25
const emptyHistory = () => [null]

export function useRealmCalls(path) {
  const [state, setState] = useState(() => path ? loadingRealmCallsState(path) : idleRealmCallsState(null))
  const activeRef = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)
  const failedRequest = useRef(null)
  const effectiveState = selectRealmCallsStateForPath(state, path)

  const loadPage = useCallback((cursor, targetIndex, nextHistory, mode = 'initial') => {
    if (!path || activeRef.current) return
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    const requestedPath = path
    const requestedHistory = nextHistory ?? emptyHistory()
    activeRef.current = true
    if (mode === 'page') {
      setState((current) => ({ ...selectRealmCallsStateForPath(current, requestedPath), path: requestedPath, pageLoading: true, pageError: false }))
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
      setState({
        path: requestedPath,
        items: rows,
        pagination: response.pagination ?? null,
        loading: false,
        pageLoading: false,
        initialError: false,
        pageError: false,
        unavailable: false,
        pageIndex: targetIndex,
        cursorHistory: requestedHistory,
      })
      failedRequest.current = null
    }).catch((requestError) => {
      if (id !== requestId.current || requestError?.name === 'AbortError') return
      if (requestError?.status === 409) {
        setState((current) => ({ ...selectRealmCallsStateForPath(current, requestedPath), path: requestedPath, loading: false, pageLoading: false, unavailable: true }))
        failedRequest.current = null
        return
      }
      if (mode === 'page') {
        setState((current) => ({ ...selectRealmCallsStateForPath(current, requestedPath), path: requestedPath, pageLoading: false, pageError: true }))
        failedRequest.current = { cursor, targetIndex, history: requestedHistory, mode }
      } else {
        setState((current) => ({ ...selectRealmCallsStateForPath(current, requestedPath), path: requestedPath, loading: false, pageLoading: false, initialError: true }))
        failedRequest.current = { cursor: null, targetIndex: 0, history: emptyHistory(), mode: 'initial' }
      }
    }).finally(() => {
      if (id !== requestId.current) return
      activeRef.current = false
    })
  }, [path])

  const retry = useCallback(() => {
    const failed = failedRequest.current
    if (failed) loadPage(failed.cursor, failed.targetIndex, failed.history, failed.mode)
    else loadPage(null, 0, emptyHistory(), 'initial')
  }, [loadPage])

  const loadOlder = useCallback(() => {
    const cursor = getRealmCallsNextCursor(effectiveState.pagination)
    if (activeRef.current || effectiveState.loading || effectiveState.pageLoading || !cursor) return
    const history = [...effectiveState.cursorHistory.slice(0, effectiveState.pageIndex + 1), cursor]
    loadPage(cursor, effectiveState.pageIndex + 1, history, 'page')
  }, [effectiveState.cursorHistory, effectiveState.loading, effectiveState.pageIndex, effectiveState.pageLoading, effectiveState.pagination, loadPage])

  const loadNewer = useCallback(() => {
    if (activeRef.current || effectiveState.loading || effectiveState.pageLoading || effectiveState.pageIndex === 0) return
    const targetIndex = effectiveState.pageIndex - 1
    loadPage(effectiveState.cursorHistory[targetIndex], targetIndex, effectiveState.cursorHistory, 'page')
  }, [effectiveState.cursorHistory, effectiveState.loading, effectiveState.pageIndex, effectiveState.pageLoading, loadPage])

  useEffect(() => {
    controller.current?.abort()
    requestId.current += 1
    activeRef.current = false
    failedRequest.current = null
    if (!path) {
      setState(idleRealmCallsState(null))
      return undefined
    }
    loadPage(null, 0, emptyHistory(), 'initial')
    return () => {
      requestId.current += 1
      controller.current?.abort()
    }
  }, [loadPage, path])

  const nextCursor = getRealmCallsNextCursor(effectiveState.pagination)
  return {
    ...effectiveState,
    retry,
    loadOlder,
    loadNewer,
    canLoadOlder: nextCursor !== null,
    canLoadNewer: effectiveState.pageIndex > 0,
  }
}
