const NAMESPACE_DISPLAY_LIMIT = 20
const NAMESPACE_HEAD_LENGTH = 8
const NAMESPACE_TAIL_LENGTH = 7

export function compactNamespace(value) {
  if (typeof value !== 'string' || value.length === 0) return ''
  if (value.length <= NAMESPACE_DISPLAY_LIMIT) return value
  return `${value.slice(0, NAMESPACE_HEAD_LENGTH)}…${value.slice(-NAMESPACE_TAIL_LENGTH)}`
}

export function applicationPresentation(item) {
  const curated = item?.application?.display_name
  if (typeof curated === 'string' && curated.length > 0) return { label: curated, title: undefined }
  const namespace = typeof item?.namespace_key === 'string' ? item.namespace_key : ''
  return { label: compactNamespace(namespace), title: namespace || undefined }
}
