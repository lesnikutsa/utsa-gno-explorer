import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealmMetadata, getRealmMetadataFile } from '../services/api'

const preferredFile = (files = []) => files.find((file) => file.file_kind === 'gno_source')
  || files.find((file) => file.file_kind === 'gno_test') || files[0] || null

export function useRealmMetadata(path) {
  const metadataController = useRef(null)
  const fileController = useRef(null)
  const [state, setState] = useState({ loading: Boolean(path), data: null, notFound: false, error: false })
  const [source, setSource] = useState({ loading: false, data: null, error: false })

  const selectFile = useCallback((filename) => {
    fileController.current?.abort()
    if (!path || !filename) return
    const controller = new AbortController()
    fileController.current = controller
    setSource({ loading: true, data: null, error: false })
    getRealmMetadataFile({ path, filename, signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setSource({ loading: false, data, error: false })
    }).catch((error) => {
      if (error?.name !== 'AbortError') setSource({ loading: false, data: null, error: true })
    })
  }, [path])

  useEffect(() => {
    metadataController.current?.abort()
    fileController.current?.abort()
    setSource({ loading: false, data: null, error: false })
    if (!path) return undefined
    const controller = new AbortController()
    metadataController.current = controller
    setState({ loading: true, data: null, notFound: false, error: false })
    getRealmMetadata({ path, signal: controller.signal }).then((data) => {
      if (controller.signal.aborted) return
      setState({ loading: false, data, notFound: false, error: false })
      const initial = preferredFile(data.files)
      if (initial) selectFile(initial.filename)
    }).catch((error) => {
      if (error?.name === 'AbortError') return
      setState({ loading: false, data: null, notFound: error?.status === 404, error: error?.status !== 404 })
    })
    return () => { controller.abort(); fileController.current?.abort() }
  }, [path, selectFile])

  return { ...state, source, selectFile }
}
