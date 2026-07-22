import { useEffect, useState } from 'react'

import { CopyButton } from '../components/CopyButton'
import { ProposerIdentity } from '../components/ProposerIdentity'
import { TransactionDecodeBadge } from '../components/TransactionDecodeBadge'
import { relativeTime } from '../utils/time'

const isValidHeight = (height) => /^[1-9]\d*$/.test(height)

function RelativeTransactionTime({ value }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timerId = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timerId)
  }, [])
  return <small>{relativeTime(value, now)}</small>
}

function StatePanel({ title, message, retry, blockHref }) {
  return (
    <section className="panel transaction-detail__state">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
      <div className="transaction-detail__state-actions">
        <a className="transaction-detail__back" href="/blocks">← Back to Blocks</a>
        {blockHref && <a className="transaction-detail__back" href={blockHref}>← Back to Block</a>}
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

export function TransactionDetail({ transactionDetail, routeHeight }) {
  const { transaction, loading, notFound, invalidRoute, error, retry } = transactionDetail
  const blockHref = isValidHeight(routeHeight) ? `/blocks/${encodeURIComponent(routeHeight)}` : null

  if (loading) return <StatePanel title="Loading transaction details…" blockHref={blockHref} />
  if (invalidRoute) return <StatePanel title="Invalid transaction location" message="The block height and transaction index must be valid non-negative integers, and the block height must be positive." blockHref={blockHref} />
  if (notFound) return <StatePanel title="Transaction not found" message="This transaction has not been indexed or does not exist." blockHref={blockHref} />
  if (error) return <StatePanel title="Transaction details are currently unavailable" message="The Explorer API could not load this transaction." retry={retry} blockHref={blockHref} />

  const canonicalBlockHref = `/blocks/${transaction.block_height}`
  return (
    <article className="transaction-detail" aria-labelledby="transaction-detail-title">
      <a className="transaction-detail__back" href={canonicalBlockHref}>← Back to Block #{transaction.block_height}</a>
      <header className="transaction-detail__header">
        {transaction.tx_hash ? <>
          <span className="transaction-detail__eyebrow">Transaction</span>
          <div className="transaction-detail__copy-row">
            <h1 className="transaction-detail__heading-hash mono" id="transaction-detail-title">{transaction.tx_hash}</h1>
            <CopyButton value={transaction.tx_hash} label="transaction hash" />
          </div>
        </> : <h1 id="transaction-detail-title">Transaction #{transaction.index}</h1>}
        <p>Included at index #{transaction.index} in finalized block #{transaction.block_height}.</p>
      </header>

      <section className="panel transaction-detail__section" aria-labelledby="transaction-information-title">
        <div className="panel__heading"><h2 id="transaction-information-title">Transaction Information</h2></div>
        <div className="transaction-detail__grid">
          <div className="transaction-detail__field"><span className="transaction-detail__label">Block</span><a className="transaction-detail__block-link accent-value mono" href={canonicalBlockHref}>#{transaction.block_height}</a></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Transaction Index</span><strong className="transaction-detail__value mono">#{transaction.index}</strong></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Block Time</span><strong className="transaction-detail__value mono">{transaction.block_time}</strong><RelativeTransactionTime value={transaction.block_time} /></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Proposer</span><ProposerIdentity address={transaction.proposer_address} moniker={transaction.proposer_moniker} showFullAddress /></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Block Hash</span><div className="transaction-detail__copy-row"><strong className="transaction-detail__value transaction-detail__hash mono">{transaction.block_hash}</strong><CopyButton value={transaction.block_hash} label="block hash" /></div></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Base64 Decode</span><TransactionDecodeBadge status={transaction.decode_status} /></div>
        </div>
      </section>

      <section className="panel transaction-detail__section" aria-labelledby="transaction-size-title">
        <div className="panel__heading"><h2 id="transaction-size-title">Transaction Size</h2></div>
        <div className="transaction-detail__size-grid">
          <div className="transaction-detail__field"><span className="transaction-detail__label">Base64 Length</span><strong className="transaction-detail__value mono">{transaction.raw_base64_length}</strong></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Decoded Bytes</span><strong className="transaction-detail__value mono">{transaction.decoded_byte_length ?? '—'}</strong></div>
        </div>
      </section>

      <section className="panel transaction-detail__section transaction-detail__raw" aria-labelledby="raw-transaction-title">
        <div className="panel__heading"><h2 id="raw-transaction-title">Raw Transaction</h2><CopyButton value={transaction.raw_base64} label="raw transaction Base64" /></div>
        <pre className="transaction-detail__raw-value mono">{transaction.raw_base64}</pre>
      </section>

      <p className="transaction-detail__notice">Transaction type, sender, execution result, gas, fee, and human-readable message details are not indexed by this Explorer yet.</p>
    </article>
  )
}
