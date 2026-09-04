import { CopyButton } from '../components/CopyButton'
import { TransactionExecutionBadge } from '../components/TransactionExecutionBadge'
import { useCosmosResource } from '../hooks/useCosmosResource'
import '../styles/cosmos-transaction-detail.css'

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
const objectValue = (value) => Object.entries(value).map(([key, item]) => `${key}: ${item}`).join(' · ')
const FieldValue = ({ value, assets }) => {
  if (Array.isArray(value)) {
    const coins = value.every((item) => item && typeof item === 'object' && 'denom' in item && 'amount' in item)
    return coins ? value.map((item) => coin(item, assets)).join(', ') : value.map(objectValue).join('; ')
  }
  if (value && typeof value === 'object') return 'denom' in value && 'amount' in value ? coin(value, assets) : objectValue(value)
  return value
}

export function CosmosTransactionDetail({ network, height, index }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/blocks/${height}/transactions/${index}`, null)
  if (resource.loading) return <p>Loading transaction…</p>
  if (!resource.data) return <p className="cosmos-error">{resource.error}</p>
  const tx = resource.data
  return <div className="cosmos-block-detail cosmos-transaction-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/blocks/${height}`}>← Back to Block #{Number(height).toLocaleString()}</a><div className="cosmos-title"><h1>Transaction #{tx.index}</h1></div>
    <section className="cosmos-detail-summary panel"><div><span>Status</span><strong><TransactionExecutionBadge status={tx.success ? 'success' : 'failed'} /></strong></div><div><span>Block</span><strong><a className="table-link accent-value" href={`/networks/${network.id}/blocks/${tx.height}`}>#{tx.height.toLocaleString()}</a></strong></div><div><span>Time</span><strong><time dateTime={tx.timestamp} title={tx.timestamp}>{utc(tx.timestamp)}</time></strong></div></section>
    <section className="panel cosmos-detail-card"><h2>Transaction Information</h2><dl><dt>TX hash</dt><dd><span className="cosmos-copy-value"><code className="cosmos-hash-value" title={tx.tx_hash}>{tx.tx_hash}</code><CopyButton value={tx.tx_hash} label="Copy transaction hash" /></span></dd><dt>Code</dt><dd>{tx.code}</dd>{!tx.success && tx.codespace ? <><dt>Codespace</dt><dd>{tx.codespace}</dd></> : null}{!tx.success && tx.error_log ? <><dt>Execution error</dt><dd className="cosmos-transaction-error">{tx.error_log}</dd></> : null}<dt>Transaction index</dt><dd>{tx.index}</dd><dt>Gas used</dt><dd>{tx.gas_used?.toLocaleString() ?? '—'}</dd><dt>Gas wanted</dt><dd>{tx.gas_wanted?.toLocaleString() ?? '—'}</dd><dt>Fee</dt><dd>{tx.fee?.amount?.length ? tx.fee.amount.map((item) => coin(item, network.assets)).join(', ') : '—'}</dd><dt>Memo</dt><dd>{tx.memo || '—'}</dd><dt>Message count</dt><dd>{tx.message_count}</dd></dl><details><summary>More transaction details</summary><dl><dt>Fee gas limit</dt><dd>{tx.fee?.gas_limit?.toLocaleString() ?? '—'}</dd><dt>Raw status code</dt><dd>{tx.code}</dd></dl></details></section>
    <section className="panel cosmos-detail-card"><h2>Messages <span>{tx.messages.length}</span></h2>{tx.messages.map((message, messageIndex) => <div className="cosmos-message" key={`${message.type_url}-${messageIndex}`}><div className="cosmos-message__heading"><span className="accent-value mono">#{messageIndex}</span><h3>{message.action}</h3></div><code>{message.type_url}</code>{message.fields.length ? <details className="cosmos-message__details"><summary>Details</summary><dl>{message.fields.map((field, fieldIndex) => <div className="cosmos-message__field" key={`${field.label}-${fieldIndex}`}><dt>{field.label}</dt><dd><FieldValue value={field.value} assets={network.assets} /></dd></div>)}</dl></details> : <p>No safely decoded fields are available.</p>}</div>)}</section>
    <details className="panel cosmos-normalized-json"><summary>Normalized JSON</summary><pre>{JSON.stringify(tx, null, 2)}</pre></details>
  </div>
}
