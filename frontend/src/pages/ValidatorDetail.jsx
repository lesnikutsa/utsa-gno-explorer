import { CopyButton } from '../components/CopyButton'
import { StatusBadge } from '../components/StatusBadge'
import {
  SIGNING_STATUSES,
  ValidatorSigningStrip,
  getSigningStatusLabel,
  normalizeSigningStatus,
} from '../components/ValidatorSigningStrip'
import { formatIntegerString, getValidatorHealth } from '../utils/validatorHealth'
import { hasValidatorMoniker } from '../utils/validatorIdentity'

const present = (value) => value !== null && value !== undefined && value !== ''
const formatHeight = (value) => present(value) ? `#${formatIntegerString(value)}` : '—'
const formatPercent = (value) => {
  if (!present(value)) return '—'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : '—'
}

function StatePanel({ title, message, retry }) {
  return (
    <section className="panel validator-detail__state">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
      <div className="validator-detail__state-actions">
        <a className="validator-detail__back" href="/validators">← Back to Validators</a>
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

function AddressField({ label, value, copyLabel }) {
  return (
    <div className="validator-detail__field">
      <span className="validator-detail__label">{label}</span>
      {present(value) ? (
        <div className="validator-detail__copy-row">
          <strong className="validator-detail__value validator-detail__address mono">{value}</strong>
          <CopyButton value={value} label={copyLabel} />
        </div>
      ) : <strong className="validator-detail__value">—</strong>}
    </div>
  )
}

function Field({ label, children, mono = false }) {
  return <div className="validator-detail__field"><span className="validator-detail__label">{label}</span><strong className={`validator-detail__value${mono ? ' mono' : ''}`}>{children}</strong></div>
}

function HeightField({ label, value }) {
  return <Field label={label} mono>{present(value) ? <a href={`/blocks/${value}`}>{formatHeight(value)}</a> : '—'}</Field>
}

const formatCount = (value) => {
  if (!present(value)) return '—'
  const number = Number(value)
  return Number.isFinite(number) ? formatIntegerString(value) : '—'
}

export function ValidatorDetail({ validatorDetail }) {
  const { validator, loading, notFound, invalidAddress, error, retry } = validatorDetail

  if (loading) return <StatePanel title="Loading validator details…" />
  if (invalidAddress) return <StatePanel title="Invalid validator address" message="The requested signing address is not valid." />
  if (notFound) return <StatePanel title="Validator not found" message="This validator has not been indexed or does not exist." />
  if (error) return <StatePanel title="Validator details are currently unavailable" message="The Explorer API could not load this validator." retry={retry} />

  const active = validator.current.active
  const status = active ? 'Active' : 'Inactive'

  return (
    <article className="validator-detail" aria-labelledby="validator-detail-title">
      <a className="validator-detail__back" href="/validators">← Back to Validators</a>
      <header className="validator-detail__header">
        <h1 id="validator-detail-title">{hasValidatorMoniker(validator) ? validator.moniker : 'Validator'}</h1>
      </header>

      <section className="panel validator-detail__section" aria-labelledby="validator-current-status-title">
        <div className="panel__heading"><h2 id="validator-current-status-title">Current Status</h2></div>
        <div className="validator-detail__grid validator-detail__grid--status">
          <div className="validator-detail__field">
            <span className="validator-detail__label">Status</span>
            <strong className={`validator-detail__value validator-detail__value--${active ? 'success' : 'danger'}`}>{status}</strong>
          </div>
          <Field label="Indexed Height" mono>{formatHeight(validator.current.height)}</Field>
          <Field label="Voting Power" mono>{present(validator.current.voting_power) ? validator.current.voting_power : '—'}</Field>
          <Field label="Voting Power Share" mono>{formatPercent(validator.current.voting_power_percent)}</Field>
          <Field label="Proposer Priority" mono>{present(validator.current.proposer_priority) ? validator.current.proposer_priority : '—'}</Field>
        </div>
      </section>

      <SigningHistory validator={validator} />

      <section className="panel validator-detail__section" aria-labelledby="validator-identity-title">
        <div className="panel__heading"><h2 id="validator-identity-title">Validator Identity</h2></div>
        <div className="validator-detail__grid validator-detail__grid--identity">
          <AddressField label="Signing Address" value={validator.address} copyLabel="signing address" />
          <AddressField label="Operator Address" value={validator.operator_address} copyLabel="operator address" />
          <AddressField label="Signing PubKey (gpub)" value={validator.signing_pubkey} copyLabel="signing public key" />
          <Field label="Consensus Key Type (RPC)" mono>{present(validator.public_key_type) ? validator.public_key_type : '—'}</Field>
          <AddressField label="Consensus Public Key (RPC)" value={validator.public_key_value} copyLabel="validator public key" />
        </div>
      </section>

      <section className="panel validator-detail__section" aria-labelledby="validator-profile-title">
        <div className="panel__heading"><h2 id="validator-profile-title">Validator Profile</h2></div>
        <div className="validator-detail__grid validator-detail__grid--profile">
          <Field label="Description">{present(validator.description) ? validator.description : '—'}</Field>
        </div>
      </section>

    </article>
  )
}

function SigningHistory({ validator }) {
  const history = validator.signing_history && typeof validator.signing_history === 'object' ? validator.signing_history : {}
  const uptime = validator.uptime_100 && typeof validator.uptime_100 === 'object' ? validator.uptime_100 : {}
  const requiredCounters = ['active_blocks', 'signed_blocks', 'nil_blocks', 'absent_blocks', 'invalid_blocks', 'unknown_blocks']
  const hasCompleteCounters = requiredCounters.every((counter) => present(uptime[counter]) && Number.isFinite(Number(uptime[counter])))
  const health = hasCompleteCounters
    ? getValidatorHealth(uptime)
    : { label: 'No data', tone: 'neutral' }
  // The detail API already returns items in chronological (oldest-to-newest) order.
  const items = Array.isArray(history.items) ? history.items : []
  const counts = Object.fromEntries(SIGNING_STATUSES.map((status) => [status, 0]))
  items.forEach((item) => { counts[normalizeSigningStatus(item?.status)] += 1 })
  const blocks = items.map((item) => ({ height: item?.height, time: item?.time }))
  const statuses = items.map((item) => item?.status)

  return (
    <section className="panel validator-detail__section" aria-labelledby="validator-signing-history-title">
      <div className="panel__heading"><h2 id="validator-signing-history-title">Signing History</h2></div>
      <div className="signing-history__range">
        <HeightField label="From Block" value={history.start_height} />
        <HeightField label="To Block" value={history.end_height} />
        <Field label="Network Blocks" mono>{formatCount(history.network_blocks)}</Field>
        <Field label="Uptime" mono>{formatPercent(uptime.uptime_percent)}</Field>
        <div className="validator-detail__field">
          <span className="validator-detail__label">Health</span>
          <StatusBadge tone={health.tone}>{health.label}</StatusBadge>
        </div>
      </div>
      <div className="signing-history__strip">
        <ValidatorSigningStrip blocks={blocks} statuses={statuses} address={validator.address} />
      </div>
      <div className="signing-history__legend" aria-label="Signing status legend and counts">
        {SIGNING_STATUSES.map((status) => (
          <div className="signing-history__legend-item" key={status}>
            <span className={`signing-strip__segment signing-strip__segment--${status}`} aria-hidden="true" />
            <span>{getSigningStatusLabel(status)}</span>
            <strong className="mono">{formatIntegerString(counts[status])}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}
