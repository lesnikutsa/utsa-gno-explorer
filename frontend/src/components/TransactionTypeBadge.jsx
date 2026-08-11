import { transactionTypeVariant } from './transactionTypeVariant'

export function TransactionTypeBadge({ children, title }) {
  const variant = transactionTypeVariant(children)

  return <span className={`transaction-type-badge transaction-type-badge--${variant}`} title={title}>{children}</span>
}
