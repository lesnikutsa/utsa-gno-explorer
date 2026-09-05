export function CosmosAccountLink({ networkId, address, children, className = '', title }) {
  if (!networkId || !address) return children ?? null
  return <a
    className={className || undefined}
    href={`/networks/${encodeURIComponent(networkId)}/accounts/${encodeURIComponent(address)}`}
    title={title ?? address}
    style={{ color: 'inherit', textDecoration: 'none' }}
  >{children ?? address}</a>
}
