import { CopyButton } from '../components/CopyButton'
import { StatusBadge } from '../components/StatusBadge'
import { formatIntegerString } from '../utils/validatorHealth'
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
        <div>
          <h1 id="validator-detail-title">{hasValidatorMoniker(validator) ? validator.moniker : 'Validator'}</h1>
          <p>Consensus validator details indexed by UTSA Explorer.</p>
        </div>
        <StatusBadge tone={active ? 'success' : 'neutral'}>{status}</StatusBadge>
      </header>

      <section className="panel validator-detail__section" aria-labelledby="validator-identity-title">
        <div className="panel__heading"><h2 id="validator-identity-title">Validator Identity</h2></div>
        <div className="validator-detail__grid">
          <AddressField label="Signing Address" value={validator.address} copyLabel="signing address" />
          <AddressField label="Operator Address" value={validator.operator_address} copyLabel="operator address" />
          <Field label="Server Type">{present(validator.server_type) ? validator.server_type : '—'}</Field>
          <Field label="Profile Source Height" mono>{formatHeight(validator.valoper_source_height)}</Field>
        </div>
      </section>

      <section className="panel validator-detail__section" aria-labelledby="validator-current-status-title">
        <div className="panel__heading"><h2 id="validator-current-status-title">Current Status</h2></div>
        <div className="validator-detail__grid validator-detail__grid--status">
          <Field label="Status">{status}</Field>
          <Field label="Indexed Height" mono>{formatHeight(validator.current.height)}</Field>
          <Field label="Voting Power" mono>{present(validator.current.voting_power) ? validator.current.voting_power : '—'}</Field>
          <Field label="Voting Power Share" mono>{formatPercent(validator.current.voting_power_percent)}</Field>
          <Field label="Proposer Priority" mono>{present(validator.current.proposer_priority) ? validator.current.proposer_priority : '—'}</Field>
        </div>
      </section>
    </article>
  )
}
