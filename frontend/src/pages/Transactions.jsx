import { DataTable } from '../components/DataTable'
import { TransactionTypeBadge } from '../components/TransactionTypeBadge'
import { TransactionExecutionBadge } from '../components/TransactionExecutionBadge'
import { GasValue } from '../components/GasValue'
import { relativeTime } from '../utils/time'

const transactionHref = (transaction) => `/blocks/${encodeURIComponent(transaction.block_height)}/transactions/${encodeURIComponent(transaction.index)}`
const shortHash = (value) => value ? `${value.slice(0, 10)}…${value.slice(-8)}` : 'Unavailable'

const columns = [
  {
    key: 'operation',
    label: 'Type',
    render: (transaction) => <TransactionTypeBadge title={transaction.type !== 'unknown' ? transaction.type : undefined}>{transaction.operation}</TransactionTypeBadge>,
  },
  {
    key: 'tx_hash',
    label: 'TX Hash',
    render: (transaction) => (
      <div className="transactions-table__hash-cell">
        <a
          className="transactions-table__hash table-link mono"
          href={transactionHref(transaction)}
          title={transaction.tx_hash || undefined}
          aria-label={`Open transaction ${transaction.tx_hash || 'with unavailable hash'} in block #${transaction.block_height}`}
        >
          <span className="transactions-table__hash-text">{shortHash(transaction.tx_hash)}</span>
        </a>
      </div>
    ),
  },
  {
    key: 'block_time',
    label: 'Time',
    render: (transaction) => <time dateTime={transaction.block_time} title={transaction.block_time}>{relativeTime(transaction.block_time)}</time>,
  },
  {
    key: 'block_height',
    label: 'Block',
    render: (transaction) => <a className="table-link" href={`/blocks/${encodeURIComponent(transaction.block_height)}`} aria-label={`Open block #${transaction.block_height}`}><span className="blocks-table__height accent-value mono">#{transaction.block_height.toLocaleString()}</span></a>,
  },
  {
    key: 'execution_status',
    label: 'Status',
    render: (transaction) => <TransactionExecutionBadge status={transaction.execution_status} />,
  },
  {
    key: 'gas_used',
    label: 'Gas Used',
    render: (transaction) => <GasValue used={transaction.gas_used} wanted={transaction.gas_wanted} />,
  },
]

export function Transactions({ transactionsPage }) {
  const { transactions, loading, error, pageIndex, canLoadOlder, retry, loadOlder, loadNewer } = transactionsPage
  const emptyMessage = error ? 'Transactions are currently unavailable.' : 'No transactions indexed yet.'

  return (
    <section className="blocks-page transactions-page" aria-labelledby="transactions-page-title">
      <header className="blocks-page__header">
        <div>
          <h1 id="transactions-page-title">Transactions</h1>
          <p>Latest transactions indexed by UTSA Explorer.</p>
        </div>
        {error && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading}>Retry</button>}
      </header>

      <div className="panel blocks-page__table transactions-page__table">
        <DataTable columns={columns} rows={transactions} rowKey={(transaction) => `${transaction.block_height}:${transaction.index}`} loading={loading} emptyMessage={emptyMessage} />
      </div>

      <nav className="blocks-pagination" aria-label="Transactions pagination">
        <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer transactions</button>
        <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
        <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older transactions</button>
      </nav>
    </section>
  )
}
