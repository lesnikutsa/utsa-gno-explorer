import { useEffect, useRef, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { TransactionTypeBadge } from '../components/TransactionTypeBadge'
import { AdditionalMessageBadge } from '../components/AdditionalMessageBadge'
import { TransactionExecutionBadge } from '../components/TransactionExecutionBadge'
import { GasValue } from '../components/GasValue'
import { relativeTime } from '../utils/time'
import { shortTransactionHash } from '../utils/transactionHash'

const transactionHref = (transaction) => `/blocks/${encodeURIComponent(transaction.block_height)}/transactions/${encodeURIComponent(transaction.index)}`

const columns = [
  {
    key: 'operation',
    label: 'Type',
    render: (transaction) => (
      <div className="transactions-table__type-cell">
        <TransactionTypeBadge title={transaction.type !== 'unknown' ? transaction.type : undefined}>{transaction.operation}</TransactionTypeBadge>
        <AdditionalMessageBadge messageCount={transaction.message_count} />
      </div>
    ),
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
          <span className="transactions-table__hash-text">{shortTransactionHash(transaction.tx_hash, 'Unavailable')}</span>
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
  const previousTransactionIds = useRef(null)
  const [newTransactionIds, setNewTransactionIds] = useState(new Set())
  const { transactions, loading, manualRefreshing, error, pageIndex, canLoadOlder, retry, refresh, loadOlder, loadNewer } = transactionsPage
  const emptyMessage = error ? 'Transactions are currently unavailable.' : 'No transactions indexed yet.'
  const latestMode = pageIndex === 0

  useEffect(() => {
    if (!latestMode || loading) {
      previousTransactionIds.current = null
      setNewTransactionIds(new Set())
      return undefined
    }
    if (error) {
      setNewTransactionIds(new Set())
      return undefined
    }

    const currentIds = transactions.map((transaction) => `${transaction.block_height}:${transaction.index}`)
    let animationTimer
    if (previousTransactionIds.current !== null) {
      const previousIds = new Set(previousTransactionIds.current)
      const firstExistingIndex = currentIds.findIndex((id) => previousIds.has(id))
      const leadingIds = currentIds.slice(0, firstExistingIndex === -1 ? currentIds.length : firstExistingIndex)
      if (leadingIds.length) {
        setNewTransactionIds(new Set(leadingIds))
        animationTimer = window.setTimeout(() => setNewTransactionIds(new Set()), 900)
      }
    }
    previousTransactionIds.current = currentIds
    return () => {
      if (animationTimer !== undefined) window.clearTimeout(animationTimer)
    }
  }, [error, latestMode, loading, transactions])

  return (
    <section className="blocks-page transactions-page" aria-labelledby="transactions-page-title">
      <header className="blocks-page__header">
        <div>
          <h1 id="transactions-page-title">Transactions</h1>
        </div>
        {error && transactions.length === 0 ? (
          <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading}>Retry</button>
        ) : latestMode ? (
          <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={refresh} disabled={loading || manualRefreshing}>
            {manualRefreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        ) : null}
      </header>

      <div className="panel blocks-page__table transactions-page__table">
        <DataTable columns={columns} rows={transactions} rowKey={(transaction) => `${transaction.block_height}:${transaction.index}`}
          rowClassName={(transaction) => newTransactionIds.size === 0 ? '' : newTransactionIds.has(`${transaction.block_height}:${transaction.index}`) ? 'is-new-row' : 'is-settling-row'}
          loading={loading} emptyMessage={emptyMessage} />
      </div>

      <nav className="blocks-pagination" aria-label="Transactions pagination">
        <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || manualRefreshing || pageIndex === 0}>Newer transactions</button>
        <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
        <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || manualRefreshing || !canLoadOlder}>Older transactions</button>
      </nav>
    </section>
  )
}
