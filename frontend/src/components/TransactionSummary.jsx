import { CopyButton } from './CopyButton'
import { StatusBadge } from './StatusBadge'

const DETAIL_FIELDS = [
  { key: 'sender', label: 'From', copyLabel: 'sender address', mono: true },
  { key: 'recipient', label: 'To', copyLabel: 'recipient address', mono: true },
  { key: 'amount', label: 'Amount', mono: true },
  { key: 'send', label: 'Attached Funds', mono: true },
  { key: 'package_path', label: 'Package', mono: true },
  { key: 'package_name', label: 'Package Name' },
  { key: 'function', label: 'Function', mono: true },
  { key: 'args_count', label: 'Arguments' },
  { key: 'file_count', label: 'Files' },
  { key: 'expires_at', label: 'Expires At' },
  { key: 'allow_paths_count', label: 'Allowed Paths' },
  { key: 'spend_limit', label: 'Spend Limit', mono: true },
  { key: 'spend_period', label: 'Spend Period' },
]

const STATUS_PRESENTATION = {
  parsed: { label: 'Decoded Content', tone: 'neutral' },
  unsupported: { label: 'Unsupported Type', tone: 'warning' },
  unparsed: { label: 'Not Classified', tone: 'neutral' },
  invalid: { label: 'Invalid Payload', tone: 'error' },
}

const STATUS_EXPLANATIONS = {
  unsupported: 'This transaction type is recognized, but detailed decoding is not supported yet.',
  unparsed: 'Transaction content is stored, but no supported message summary is available.',
  invalid: 'The transaction payload could not be decoded.',
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)
const isScalar = (value) => typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'

const displayValue = (value) => typeof value === 'boolean' ? (value ? 'Yes' : 'No') : value
const humanize = (value) => typeof value === 'string'
  ? value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
  : '—'

function DetailFields({ message }) {
  const fields = DETAIL_FIELDS.filter(({ key }) => isScalar(message[key]))
  if (fields.length === 0) return null

  return (
    <dl className="transaction-summary__details">
      {fields.map(({ key, label, copyLabel, mono }) => (
        <div className="transaction-summary__detail" key={key}>
          <dt>{label}</dt>
          <dd className={mono ? 'mono' : undefined}>
            <span>{displayValue(message[key])}</span>
            {copyLabel && <CopyButton value={message[key]} label={copyLabel} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function UnavailableSummary() {
  return <p className="transaction-summary__notice">Human-readable summary was not indexed for this transaction.</p>
}

export function TransactionSummary({ summary }) {
  const valid = isRecord(summary)
    && isRecord(summary.primary)
    && Array.isArray(summary.messages)
    && summary.messages.every(isRecord)
    && Object.hasOwn(STATUS_PRESENTATION, summary.parse_status)

  if (!valid) {
    return (
      <section className="panel transaction-detail__section transaction-summary" aria-labelledby="transaction-summary-title">
        <div className="panel__heading"><h2 id="transaction-summary-title">Transaction Summary</h2></div>
        <UnavailableSummary />
      </section>
    )
  }

  const status = STATUS_PRESENTATION[summary.parse_status]
  const overview = [
    ['Operation', summary.primary.label],
    ['Message Type', summary.primary.type],
    ['Category', humanize(summary.primary.category)],
    ['Action', humanize(summary.primary.action)],
    ['Messages', isScalar(summary.message_count) ? summary.message_count : '—'],
  ]
  const multipleMessages = summary.messages.length > 1

  return (
    <section className="panel transaction-detail__section transaction-summary" aria-labelledby="transaction-summary-title">
      <div className="panel__heading transaction-summary__heading">
        <div>
          <h2 id="transaction-summary-title">Transaction Summary</h2>
          {isScalar(summary.chain_family) && <small>Chain family: {summary.chain_family}</small>}
        </div>
        <span title="Content decoding status. This is not transaction execution status." aria-label={`Content decoding status: ${status.label}. This is not transaction execution status.`}>
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        </span>
      </div>

      <dl className="transaction-summary__overview">
        {overview.map(([label, value]) => (
          <div className="transaction-summary__overview-field" key={label}>
            <dt>{label}</dt>
            <dd>{isScalar(value) ? displayValue(value) : '—'}</dd>
          </div>
        ))}
      </dl>

      {STATUS_EXPLANATIONS[summary.parse_status] && (
        <p className={`transaction-summary__notice${summary.parse_status === 'invalid' ? ' transaction-summary__notice--error' : ''}`}>
          {STATUS_EXPLANATIONS[summary.parse_status]}
        </p>
      )}

      {multipleMessages ? (
        <div className="transaction-summary__messages">
          {summary.messages.map((message, index) => (
            <section className="transaction-summary__message" aria-labelledby={`transaction-summary-message-${index + 1}`} key={index}>
              <h3 id={`transaction-summary-message-${index + 1}`}>Message #{index + 1}</h3>
              <div className="transaction-summary__message-core">
                <strong>{isScalar(message.label) ? message.label : '—'}</strong>
                <span className="mono">{isScalar(message.type) ? message.type : '—'}</span>
              </div>
              <DetailFields message={message} />
            </section>
          ))}
        </div>
      ) : summary.messages.length === 1 ? <DetailFields message={summary.messages[0]} /> : null}

      {summary.messages_truncated === true && <p className="transaction-summary__notice">Some message summaries are not shown.</p>}
    </section>
  )
}
