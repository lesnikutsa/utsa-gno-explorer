export function CosmosPanel({ children, className = '' }) {
  return <section className={`card cosmos-panel ${className}`.trim()}>{children}</section>
}
