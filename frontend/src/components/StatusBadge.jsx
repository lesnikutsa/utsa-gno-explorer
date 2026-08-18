export function StatusBadge({ tone = 'neutral', children, ...props }) {
  return <span className={`status-badge status-badge--${tone}`} {...props}>{children}</span>
}
