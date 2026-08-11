import { useState } from 'react'

import { CopyButton } from './CopyButton'
import { StatusBadge } from './StatusBadge'
import { isCanonicalRealmPath, realmDetailHref } from '../utils/realm'
import { isValidArgumentValue } from '../utils/transactionArguments'

const DETAIL_FIELDS = [
  { key: 'sender', label: 'From', copyLabel: 'sender address', mono: true },
  { key: 'recipient', label: 'To', copyLabel: 'recipient address', mono: true },
  { key: 'amount', label: 'Amount', mono: true },
  { key: 'send', label: 'Attached Funds', mono: true },
  { key: 'package_path', label: 'Package', mono: true },
  { key: 'package_name', label: 'Package Name' },
  { key: 'function', label: 'Function', mono: true },
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

const CORE_FIELDS = ['type', 'category', 'action', 'label']
const STRING_DETAIL_FIELDS = [
  'sender', 'recipient', 'amount', 'send', 'package_path', 'package_name', 'function',
  'expires_at', 'spend_limit', 'spend_period',
]
const COUNT_DETAIL_FIELDS = ['args_count', 'file_count', 'allow_paths_count']

const isPlainObject = (value) => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}
const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0
const isNonNegativeInteger = (value) => Number.isInteger(value) && value >= 0
const isScalar = (value) => typeof value === 'string'
  || typeof value === 'boolean'
  || (typeof value === 'number' && Number.isFinite(value))

const hasValidDetails = (message) => STRING_DETAIL_FIELDS.every((key) => (
  message[key] === undefined || message[key] === null || typeof message[key] === 'string'
)) && COUNT_DETAIL_FIELDS.every((key) => (
  message[key] === undefined || message[key] === null || isNonNegativeInteger(message[key])
))

const hasValidCore = (value) => isPlainObject(value)
  && CORE_FIELDS.every((key) => isNonEmptyString(value[key]))

const isValidSummary = (summary) => {
  if (!isPlainObject(summary) || !Object.hasOwn(STATUS_PRESENTATION, summary.parse_status)) return false
  if (!isNonEmptyString(summary.chain_family) || !hasValidCore(summary.primary)) return false
  if (!Array.isArray(summary.messages) || summary.messages.length > 20) return false
  if (!summary.messages.every((message) => hasValidCore(message) && hasValidDetails(message))) return false
  if (summary.message_count !== null && !isNonNegativeInteger(summary.message_count)) return false
  if (typeof summary.messages_truncated !== 'boolean') return false
  if (summary.message_count !== null && summary.message_count < summary.messages.length) return false
  if (summary.message_count !== null
    && summary.message_count > summary.messages.length
    && summary.messages_truncated !== true) return false
  if (summary.messages.length > 0
    && !CORE_FIELDS.every((key) => summary.messages[0][key] === summary.primary[key])) return false
  return true
}

const displayValue = (value) => typeof value === 'boolean' ? (value ? 'Yes' : 'No') : value
const humanize = (value) => typeof value === 'string'
  ? value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
  : '—'

function RealmPathLink({ path }) {
  if (!isCanonicalRealmPath(path)) return path
  return (
    <a
      className="transaction-summary__realm-link"
      href={realmDetailHref(path)}
      onClick={(event) => event.stopPropagation()}
    >
      {path}
    </a>
  )
}

function DetailFields({ message, showArgumentFallback }) {
  const fields = DETAIL_FIELDS.filter(({ key }) => isScalar(message[key]))
  if (showArgumentFallback && isScalar(message.args_count)) {
    fields.push({ key: 'args_count', label: 'Arguments' })
  }
  if (fields.length === 0) return null
  const hasCrowdedSender = fields.length >= 4
    && fields.some(({ key }) => key === 'sender')

  return (
    <dl className={`transaction-summary__details${hasCrowdedSender ? ' transaction-summary__details--sender-priority' : ''}`}>
      {fields.map(({ key, label, copyLabel, mono }) => (
        <div className={`transaction-summary__detail${key === 'sender' ? ' transaction-summary__detail--sender' : ''}`} key={key}>
          <dt>{label}</dt>
          <dd className={mono ? 'mono' : undefined}>
            <span>{displayValue(message[key])}</span>
            {copyLabel && typeof message[key] === 'string' && <CopyButton value={message[key]} label={copyLabel} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function Arguments({ detail, count }) {
  if (!detail) return null
  return (
    <section className="transaction-summary__arguments" aria-label="Message arguments">
      <h4>Arguments · {isScalar(count) ? count : detail.values.length}</h4>
      {detail.values.length > 0 && <ol>
        {detail.values.map((value, index) => <li key={index}><code>{value === '' ? '—' : value}</code></li>)}
      </ol>}
      {detail.truncated && <p>Some argument values were shortened or are not shown.</p>}
    </section>
  )
}

function validArgumentDetails(messageArguments) {
  if (!Array.isArray(messageArguments) || messageArguments.length > 20) return new Map()
  const result = new Map()
  let previous = -1
  for (const detail of messageArguments) {
    if (!isPlainObject(detail) || !isNonNegativeInteger(detail.message_index) || detail.message_index <= previous) return new Map()
    if (!Array.isArray(detail.values) || detail.values.length > 16 || !detail.values.every(isValidArgumentValue)) return new Map()
    if (typeof detail.truncated !== 'boolean') return new Map()
    result.set(detail.message_index, detail)
    previous = detail.message_index
  }
  return result
}

function UnavailableSummary() {
  return <p className="transaction-summary__notice">Human-readable summary was not indexed for this transaction.</p>
}

function MessageDisclosure({ message, index, argumentDetail }) {
  const [open, setOpen] = useState(index === 0)
  const location = isScalar(message.package_path) ? message.package_path : message.package_name
  return (
    <details
      className="transaction-summary__message"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary id={`transaction-summary-message-${index + 1}`}>
        <strong>Message #{index + 1}</strong>
        <span>{isScalar(message.label) ? message.label : '—'}</span>
        {isScalar(location) && <span className="mono">
          {message.package_path === location
            ? <RealmPathLink path={location} />
            : location}
        </span>}
        {isScalar(message.function) && <span className="mono">{message.function}</span>}
        {isScalar(message.args_count) && <span>{message.args_count} arguments</span>}
      </summary>
      <div className="transaction-summary__message-content" aria-labelledby={`transaction-summary-message-${index + 1}`}>
        <DetailFields message={message} showArgumentFallback={!argumentDetail} />
        <Arguments detail={argumentDetail} count={message.args_count} />
      </div>
    </details>
  )
}

export function TransactionSummary({ summary, messageArguments = null }) {
  if (!isValidSummary(summary)) {
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
  const argumentDetails = validArgumentDetails(messageArguments)

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

      {summary.messages.length > 0 && (
        <div className="transaction-summary__messages">
          {summary.messages.map((message, index) => <MessageDisclosure
            message={message}
            index={index}
            argumentDetail={argumentDetails.get(index)}
            key={index}
          />)}
        </div>
      )}

      {summary.messages_truncated === true && <p className="transaction-summary__notice">Some message summaries are not shown.</p>}
    </section>
  )
}
