import { useEffect, useState } from 'react'

import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { relativeTime } from '../utils/time'

const transactionColumns = [
  { key: 'index', label: 'Index', render: (transaction) => <span className="mono">#{transaction.index}</span> },
  {
    key: 'raw_base64',
    label: 'Raw Base64',
    render: (transaction) => <span className="transaction-raw mono" title={transaction.raw_base64}>{transaction.raw_base64}</span>,
  },
  { key: 'raw_base64_length', label: 'Base64 Length' },
  { key: 'decoded_byte_length', label: 'Decoded Bytes', render: (transaction) => transaction.decoded_byte_length ?? '—' },
  {
    key: 'decode_status',
    label: 'Decode Status',
    render: (transaction) => {
      if (transaction.decode_status === 'decoded') return <StatusBadge tone="success">Decoded</StatusBadge>
      if (transaction.decode_status === 'invalid_base64') return <StatusBadge tone="error">Invalid Base64</StatusBadge>
      return <StatusBadge>{transaction.decode_status}</StatusBadge>
    },
  },
]

const commitMetrics = [
  ['validators', 'Validators', ''],
  ['signed', 'Signed', ' block-detail__metric--success'],
  ['missed', 'Missed', ' block-detail__metric--warning'],
  ['nil', 'Nil', ''],
  ['absent', 'Absent', ''],
  ['invalid', 'Invalid', ' block-detail__metric--error'],
  ['unknown', 'Unknown', ''],
]

function RelativeBlockTime({ value }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timerId = window.setInterval(() => {
      setNow(Date.now())
    }, 30_000)

    return () => window.clearInterval(timerId)
  }, [])

  return <small>{relativeTime(value, now)}</small>
}

function StatePanel({ title, message, retry }) {
  return (
    <section className="panel block-detail__state">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
      <div className="block-detail__state-actions">
        <a className="block-detail__back" href="/blocks">← Back to Blocks</a>
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

export function BlockDetail({ blockDetail }) {
  const { block, loading, notFound, invalidHeight, error, retry } = blockDetail

  if (loading) return <StatePanel title="Loading block details…" />
  if (invalidHeight) return <StatePanel title="Invalid block height" message="The requested block height is not valid." />
  if (notFound) return <StatePanel title="Block not found" message="This block has not been indexed or does not exist." />
  if (error) return <StatePanel title="Block details are currently unavailable" message="The Explorer API could not load this block." retry={retry} />

  return (
    <article className="block-detail" aria-labelledby="block-detail-title">
      <a className="block-detail__back" href="/blocks">← Back to Blocks</a>
      <header className="block-detail__header">
        <h1 id="block-detail-title">Block #{block.height.toLocaleString()}</h1>
        <p>Finalized block details indexed by UTSA Explorer.</p>
      </header>

      <section className="panel block-detail__section" aria-labelledby="block-information-title">
        <div className="panel__heading"><h2 id="block-information-title">Block Information</h2></div>
        <div className="block-detail__grid">
          <div className="block-detail__field"><span className="block-detail__label">Height</span><strong className="block-detail__value accent-value mono">#{block.height.toLocaleString()}</strong></div>
          <div className="block-detail__field"><span className="block-detail__label">Time</span><strong className="block-detail__value mono">{block.time}</strong><RelativeBlockTime value={block.time} /></div>
          <div className="block-detail__field"><span className="block-detail__label">Proposer</span><strong className="block-detail__value mono">{block.proposer_address ?? '—'}</strong></div>
          <div className="block-detail__field"><span className="block-detail__label">Transactions</span><strong className="block-detail__value mono">{block.tx_count}</strong></div>
        </div>
      </section>

      <section className="panel block-detail__section" aria-labelledby="block-hashes-title">
        <div className="panel__heading"><h2 id="block-hashes-title">Block Hashes</h2></div>
        <div className="block-detail__hashes">
          <div className="block-detail__field"><span className="block-detail__label">Block Hash</span><strong className="block-detail__value block-detail__hash mono">{block.block_hash}</strong></div>
          <div className="block-detail__field"><span className="block-detail__label">Block Hash Base64</span><strong className="block-detail__value block-detail__hash mono">{block.block_hash_base64}</strong></div>
        </div>
      </section>

      <section className="panel block-detail__section" aria-labelledby="commit-summary-title">
        <div className="panel__heading"><h2 id="commit-summary-title">Commit Summary</h2></div>
        <div className="block-detail__commit">
          {commitMetrics.map(([key, label, modifier]) => <div className={`block-detail__metric${modifier}`} key={key}><span>{label}</span><strong className="mono">{block.commit[key]}</strong></div>)}
        </div>
      </section>

      <section className="panel block-detail__section block-detail__transactions" aria-labelledby="transactions-title">
        <div className="panel__heading"><h2 id="transactions-title">Transactions</h2></div>
        <DataTable columns={transactionColumns} rows={block.transactions} rowKey={(transaction) => transaction.index} loading={false} emptyMessage="No transactions in this block." />
      </section>
    </article>
  )
}
