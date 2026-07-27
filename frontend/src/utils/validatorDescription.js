const SECTION_MARKER = /\*\*([^*\r\n]{1,100}?):\*\*/g
const ABSOLUTE_HTTP_URL = /https?:\/\/[^\s<>"']+/gi
const TRAILING_URL_PUNCTUATION = /[.,;\)\]]+$/

const trimOuterWhitespace = (value) => value.trim()

export function parseValidatorDescription(description) {
  if (typeof description !== 'string') return { type: 'empty', preamble: '', sections: [] }

  const normalized = description.replace(/\r\n?/g, '\n').trim()
  if (!normalized) return { type: 'empty', preamble: '', sections: [] }

  const markers = [...normalized.matchAll(SECTION_MARKER)]
    .map((match) => ({
      index: match.index,
      end: match.index + match[0].length,
      label: match[1].trim(),
    }))
    .filter((marker) => marker.label)

  if (!markers.length) return { type: 'plain', content: normalized, preamble: '', sections: [] }

  const preamble = trimOuterWhitespace(normalized.slice(0, markers[0].index))
  const sections = markers.flatMap((marker, index) => {
    const nextMarker = markers[index + 1]
    const content = trimOuterWhitespace(normalized.slice(marker.end, nextMarker?.index ?? normalized.length))
    return content ? [{ label: marker.label, content }] : []
  })

  if (!preamble && !sections.length) return { type: 'empty', preamble: '', sections: [] }
  return { type: 'structured', preamble, sections }
}

export function splitValidatorDescriptionLinks(content) {
  if (typeof content !== 'string' || !content) return []

  const parts = []
  let cursor = 0
  for (const match of content.matchAll(ABSOLUTE_HTTP_URL)) {
    if (match.index > cursor) parts.push({ type: 'text', value: content.slice(cursor, match.index) })

    const punctuation = match[0].match(TRAILING_URL_PUNCTUATION)?.[0] ?? ''
    const url = punctuation ? match[0].slice(0, -punctuation.length) : match[0]
    parts.push({ type: 'link', value: url, href: url })
    if (punctuation) parts.push({ type: 'text', value: punctuation })
    cursor = match.index + match[0].length
  }

  if (cursor < content.length) parts.push({ type: 'text', value: content.slice(cursor) })
  return parts
}
