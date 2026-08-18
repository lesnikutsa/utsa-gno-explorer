import { transactionTypeVariant } from './transactionTypeVariant'
import { transactionTypeSegment } from './transactionTypeSegments'

export function TransactionTypeBadge({ children, title }) {
  const variant = transactionTypeVariant(children)
  const segment = transactionTypeSegment(children)

  return (
    <span
      aria-label={segment ? children : undefined}
      className={`transaction-type-badge transaction-type-badge--${variant}${segment ? ' transaction-type-badge--segmented' : ''}`}
      title={title}
    >
      {segment ? (
        <span aria-hidden="true" className="transaction-type-badge__segments">
          <span className="transaction-type-badge__prefix">{segment.prefix}</span>
          <span className="transaction-type-badge__action">{segment.action}</span>
        </span>
      ) : children}
    </span>
  )
}
