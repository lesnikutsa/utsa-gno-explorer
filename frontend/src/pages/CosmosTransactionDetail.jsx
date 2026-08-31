import { CopyButton } from '../components/CopyButton'
import { TransactionExecutionBadge } from '../components/TransactionExecutionBadge'
import { useCosmosResource } from '../hooks/useCosmosResource'

const utc = (value) => new Date(value).toLocaleString('en-GB', { timeZone: 'UTC' }) + ' UTC'
const coin = (value, assets) => {
  if (!value) return '—'
  const asset = assets.find((item) => item.base === value.denom)
  if (!asset) return `${value.amount} ${value.denom}`
  const padded = value.amount.padStart(asset.exponent + 1, '0')
  const whole = padded.slice(0, -asset.exponent) || '0'
  const fraction = padded.slice(-asset.exponent).replace(/0+$/, '')
  return `${whole}${fraction ? `.${fraction}` : ''} ${asset.symbol}`
}
const FieldValue = ({ value, assets }) => Array.isArray(value)
  ? value.map((item) => coin(item, assets)).join(', ')
  : typeof value === 'object' ? coin(value, assets) : value

export function CosmosTransactionDetail({ network, height, index }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/blocks/${height}/transactions/${index}`, null)
  if (resource.loading) return <p>Loading transaction…</p>
  if (!resource.data) return <p className="cosmos-error">{resource.error}</p>
  const tx = resource.data
  return <div className="cosmos-block-detail cosmos-transaction-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/blocks/${height}`}>← Back to Block #{Number(height).toLocaleString()}</a><div className="cosmos-title"><h1>Transaction #{tx.index}</h1></div>
    <section className="cosmos-detail-summary panel"><div><span>Status</span><strong><TransactionExecutionBadge status={tx.success ? 'success' : 'failed'} /></strong></div><div><span>Block</span><strong><a className="table-link accent-value" href={`/networks/${network.id}/blocks/${tx.height}`}>#{tx.height.toLocaleString()}</a></strong></div><div><span>Time</span><strong><time dateTime={tx.timestamp} title={tx.timestamp}>{utc(tx.timestamp)}</time></strong></div></section>
    <section className="panel cosmos-detail-card"><h2>Transaction Information</h2><dl><dt>TX hash</dt><dd><span className="cosmos-copy-value"><code className="cosmos-hash-value" title={tx.tx_hash}>{tx.tx_hash}</code><CopyButton value={tx.tx_hash} label="Copy transaction hash" /></span></dd><dt>Code</dt><dd>{tx.code}</dd><dt>Transaction index</dt><dd>{tx.index}</dd><dt>Gas used</dt><dd>{tx.gas_used?.toLocaleString() ?? '—'}</dd><dt>Gas wanted</dt><dd>{tx.gas_wanted?.toLocaleString() ?? '—'}</dd><dt>Fee</dt><dd>{tx.fee?.amount?.length ? tx.fee.amount.map((item) => coin(item, network.assets)).join(', ') : '—'}</dd><dt>Memo</dt><dd>{tx.memo || '—'}</dd><dt>Message count</dt><dd>{tx.message_count}</dd></dl><details><summary>More transaction details</summary><dl><dt>Fee gas limit</dt><dd>{tx.fee?.gas_limit?.toLocaleString() ?? '—'}</dd><dt>Raw status code</dt><dd>{tx.code}</dd></dl></details></section>
    <section className="panel cosmos-detail-card"><h2>Messages <span>{tx.messages.length}</span></h2>{tx.messages.map((message, messageIndex) => <div className="cosmos-message" key={`${message.type_url}-${messageIndex}`}><h3>{message.action}</h3><code>{message.type_url}</code>{message.fields.length ? <dl>{message.fields.map((field) => <><dt key={`${field.label}-label`}>{field.label}</dt><dd key={field.label}><FieldValue value={field.value} assets={network.assets} /></dd></>)}</dl> : <p>No safely decoded fields are available.</p>}</div>)}</section>
    <details className="panel cosmos-normalized-json"><summary>Normalized JSON</summary><pre>{JSON.stringify(tx, null, 2)}</pre></details>
  </div>
}
