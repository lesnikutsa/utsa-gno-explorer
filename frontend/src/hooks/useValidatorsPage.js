import { useCallback, useEffect, useRef, useState } from 'react'
import { getValidatorSigningHistory, getValidators } from '../services/api'

export const VALIDATORS_POLL_MS = 15_000
const INITIAL_RESPONSE = { height: null, total: 0, total_voting_power: '0', items: [] }

export function useValidatorsPage() {
  const [response, setResponse] = useState(INITIAL_RESPONSE)
  const [historyResponse, setHistoryResponse] = useState(null)
  const [loading, setLoading] = useState(true)
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false)
  const [manualRefreshing, setManualRefreshing] = useState(false)
  const [error, setError] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [hasSuccessfulResponse, setHasSuccessfulResponse] = useState(false)
  const [hasSuccessfulHistoryResponse, setHasSuccessfulHistoryResponse] = useState(false)
  const mounted = useRef(false)
  const inFlight = useRef(false)
  const requestId = useRef(0)
  const timer = useRef(null)
  const hasSuccessfulResponseRef = useRef(false)
  const requestRef = useRef(null)

  const clearTimer = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
  }, [])

  const scheduleRefresh = useCallback(() => {
    clearTimer()
    if (!mounted.current) return
    timer.current = window.setTimeout(() => requestRef.current?.('background'), VALIDATORS_POLL_MS)
  }, [clearTimer])

  const request = useCallback(async (mode) => {
    if (inFlight.current) return false
    clearTimer()
    inFlight.current = true
    const id = ++requestId.current
    if (mode === 'background') setBackgroundRefreshing(true)
    if (mode === 'manual') setManualRefreshing(true)

    try {
      const [initialValidatorsResult, initialHistoryResult] = await Promise.allSettled([
        getValidators(),
        getValidatorSigningHistory({ limit: 50 }),
      ])
      let validatorsResult = initialValidatorsResult
      let historyResult = initialHistoryResult
      if (validatorsResult.status === 'fulfilled' && historyResult.status === 'fulfilled' && validatorsResult.value.height !== historyResult.value.height) {
        if (validatorsResult.value.height < historyResult.value.height) {
          const reconciledValidators = await Promise.allSettled([getValidators()])
          if (reconciledValidators[0].status === 'fulfilled') validatorsResult = reconciledValidators[0]
        } else {
          const reconciledHistory = await Promise.allSettled([getValidatorSigningHistory({ limit: 50 })])
          if (reconciledHistory[0].status === 'fulfilled') historyResult = reconciledHistory[0]
        }
      }
      if (!mounted.current || id !== requestId.current) return false

      if (validatorsResult.status === 'fulfilled') {
        const historyMatched = historyResult.status === 'fulfilled'
          && validatorsResult.value.height === historyResult.value.height
        if (historyMatched) {
          setHistoryResponse(historyResult.value)
          setHasSuccessfulHistoryResponse(true)
          setHistoryError(false)
        } else {
          setHistoryError(true)
        }

        hasSuccessfulResponseRef.current = true
        setResponse(validatorsResult.value)
        setHasSuccessfulResponse(true)
        setError(false)
        setHealthState('healthy')
        return true
      }

      setError(true)
      setHealthState(hasSuccessfulResponseRef.current ? 'degraded' : 'error')
      return false
    } finally {
      if (mounted.current && id === requestId.current) {
        inFlight.current = false
        setLoading(false)
        setBackgroundRefreshing(false)
        setManualRefreshing(false)
        scheduleRefresh()
      }
    }
  }, [clearTimer, scheduleRefresh])
  requestRef.current = request

  const refresh = useCallback(() => {
    if (inFlight.current) return false
    return request('manual')
  }, [request])

  useEffect(() => {
    mounted.current = true
    request('initial')
    return () => {
      mounted.current = false
      requestId.current += 1
      inFlight.current = false
      clearTimer()
    }
  }, [clearTimer, request])

  return {
    response,
    validators: response.items,
    historyResponse,
    loading,
    backgroundRefreshing,
    manualRefreshing,
    error,
    historyError,
    healthState,
    hasSuccessfulResponse,
    hasSuccessfulHistoryResponse,
    refresh,
  }
}
