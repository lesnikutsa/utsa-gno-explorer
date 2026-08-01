import { useEffect, useState } from 'react'

import { CopyButton } from '../components/CopyButton'
import { ProposerIdentity } from '../components/ProposerIdentity'
import { TransactionDecodeBadge } from '../components/TransactionDecodeBadge'
import { TransactionSummary } from '../components/TransactionSummary'
import { TransactionExecutionBadge } from '../components/TransactionExecutionBadge'
import { GasValue } from '../components/GasValue'
import { relativeTime } from '../utils/time'
import { formatGas, formatGasUtilization } from '../utils/gas'

function RelativeTransactionTime({ value }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timerId = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timerId)
  }, [])
  return <small>{relativeTime(value, now)}</small>
}

function StatePanel({ title, message, retry }) {
  return (
    <section className="panel transaction-detail__state">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
      <div className="transaction-detail__state-actions">
        <a className="transaction-detail__back" href="/transactions">← Back to Transactions</a>
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

export function TransactionDetail({ transactionDetail }) {
  const { transaction, loading, notFound, invalidRoute, error, retry } = transactionDetail

  if (loading) return <StatePanel title="Loading transaction details…" />
  if (invalidRoute) return <StatePanel title="Invalid transaction location" message="The block height and transaction index must be valid non-negative integers, and the block height must be positive." />
  if (notFound) return <StatePanel title="Transaction not found" message="This transaction has not been indexed or does not exist." />
  if (error) return <StatePanel title="Transaction details are currently unavailable" message="The Explorer API could not load this transaction." retry={retry} />

  const canonicalBlockHref = `/blocks/${transaction.block_height}`
  return (
    <article className="transaction-detail" aria-labelledby="transaction-detail-title">
      <a className="transaction-detail__back" href="/transactions">← Back to Transactions</a>
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
          <div className="transaction-detail__field transaction-detail__field--full-width"><span className="transaction-detail__label">Block Hash</span><div className="transaction-detail__copy-row"><strong className="transaction-detail__value transaction-detail__hash mono">{transaction.block_hash}</strong><CopyButton value={transaction.block_hash} label="block hash" /></div></div>
        </div>
      </section>

      <section className="panel transaction-detail__section transaction-detail__execution" aria-labelledby="execution-result-title">
        <div className="panel__heading"><h2 id="execution-result-title">Execution Result</h2></div>
        <div className="transaction-detail__execution-grid">
          <div className="transaction-detail__field"><span className="transaction-detail__label">Status</span><TransactionExecutionBadge status={transaction.execution_status} /></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Gas Used</span><strong className="transaction-detail__value"><GasValue used={transaction.gas_used} wanted={transaction.gas_wanted} /></strong></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Gas Wanted</span><strong className="transaction-detail__value mono">{formatGas(transaction.gas_wanted)}</strong></div>
          <div className="transaction-detail__field"><span className="transaction-detail__label">Gas Utilization</span><strong className="transaction-detail__value mono">{formatGasUtilization(transaction.gas_used, transaction.gas_wanted)}</strong></div>
        </div>
        {transaction.execution_status === 'failed' && transaction.error && (
          <div className="transaction-detail__execution-error" role="alert"><strong>Execution error</strong><p>{transaction.error}</p></div>
        )}
        {transaction.execution_status == null && <p className="transaction-detail__execution-unavailable">The execution result is not available from the indexed RPC data.</p>}
        {(transaction.log || transaction.info) && (
          <details className="transaction-detail__nested-details">
            <summary>Execution Details</summary>
            <div className="transaction-detail__details-content">
              {transaction.log && <div><strong>Log</strong><pre>{transaction.log}</pre></div>}
              {transaction.info && <div><strong>Info</strong><pre>{transaction.info}</pre></div>}
            </div>
          </details>
        )}
      </section>

      <TransactionSummary summary={transaction.summary} />

      <details className="panel transaction-detail__section transaction-detail__technical">
        <summary>Technical Data</summary>
        <div className="transaction-detail__technical-content">
          <p>Low-level encoded transaction data intended for debugging and verification.</p>
          <div className="transaction-detail__size-grid">
            <div className="transaction-detail__field"><span className="transaction-detail__label">Base64 Decode status</span><TransactionDecodeBadge status={transaction.decode_status} /></div>
            <div className="transaction-detail__field"><span className="transaction-detail__label">Encoded length</span><strong className="transaction-detail__value mono">{transaction.raw_base64_length} characters</strong></div>
            <div className="transaction-detail__field"><span className="transaction-detail__label">Decoded size</span><strong className="transaction-detail__value mono">{transaction.decoded_byte_length == null ? '—' : `${transaction.decoded_byte_length} bytes`}</strong></div>
          </div>
          <div className="transaction-detail__raw">
            <div className="panel__heading"><h2>Raw Transaction Base64</h2><CopyButton value={transaction.raw_base64} label="raw transaction Base64" /></div>
            <pre className="transaction-detail__raw-value mono">{transaction.raw_base64}</pre>
          </div>
        </div>
      </details>
    </article>
  )
}
