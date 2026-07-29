import { CopyButton } from '../components/CopyButton'
import { networkProfile } from '../config/networkProfile'
import { findNativeBalance } from '../utils/account'

const present = (value) => value !== null && value !== undefined && value !== ''

function CopyValue({ value, label, href }) {
  return (
    <div className="account-detail__copy-row">
      <strong className="account-detail__value mono">{href ? <a href={href}>{value}</a> : value}</strong>
      <CopyButton value={value} label={label} />
    </div>
  )
}

function Field({ label, children, mono = false }) {
  return <div className="account-detail__field"><span className="account-detail__label">{label}</span><strong className={`account-detail__value${mono ? ' mono' : ''}`}>{children}</strong></div>
}

function StatePanel({ title, message, retry, loading = false }) {
  return (
    <section className="panel account-detail__state" role="status" aria-live="polite">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
      {loading && <div className="account-detail__skeleton" aria-hidden="true"><span /><span /><span /></div>}
      <div className="account-detail__actions">
        <a className="account-detail__back" href="/">← Back to Overview</a>
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

function sourceLabel(source) {
  try {
    return new URL(source?.rpc_url).hostname || 'RPC'
  } catch {
    return 'RPC'
  }
}

function FetchedAt({ height }) {
  if (!present(height)) return null
  return (
    <p className="account-detail__fetched">Fetched at block <a href={`/blocks/${encodeURIComponent(height)}`}>#{height}</a></p>
  )
}

function MissingAccount({ account, retry, loading, refreshError }) {
  return (
    <article className="account-detail" aria-labelledby="account-detail-title">
      <a className="account-detail__back" href="/">← Back to Overview</a>
      <header className="account-detail__header">
        <h1 id="account-detail-title">Account not found</h1>
        <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading} aria-label="Refresh missing account details">{loading ? 'Refreshing…' : 'Refresh'}</button>
      </header>
      <p className="account-detail__message">This address has no account state on the current network.</p>
      {refreshError && <p className="account-detail__refresh-error" role="status">Account refresh is currently unavailable.</p>}
      <section className="panel account-detail__compact-card" aria-labelledby="account-request-title">
        <h2 id="account-request-title">Requested address</h2>
        <CopyValue value={account.address} label="account address" />
        <p className="account-detail__source">Live RPC · {sourceLabel(account.source)}</p>
        <FetchedAt height={account.observed_height} />
      </section>
    </article>
  )
}

export function AccountDetail({ accountDetail }) {
  const { account, loading, invalidAddress, unavailable, error, retry } = accountDetail

  if (loading && !account) return <StatePanel title="Loading account…" loading />
  if (invalidAddress && !account) return <StatePanel title="Invalid account address" message="The requested account address is not valid for this network." />
  if (unavailable && !account) return <StatePanel title="Account data is temporarily unavailable" message="The Explorer could not read current account state from a fresh RPC endpoint." retry={retry} />
  if (error && !account) return <StatePanel title="Account details are currently unavailable" retry={retry} />
  if (!account?.found) return <MissingAccount account={account} retry={retry} loading={loading} refreshError={invalidAddress || unavailable || error} />

  const balances = Array.isArray(account.balances) ? account.balances : []
  const primary = findNativeBalance(balances, networkProfile.nativeDenom)

  return (
    <article className="account-detail" aria-labelledby="account-detail-title">
      <a className="account-detail__back" href="/">← Back to Overview</a>
      <header className="account-detail__header">
        <div><h1 id="account-detail-title">Account</h1><CopyValue value={account.address} label="account address" /></div>
        <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading} aria-label="Refresh account details">{loading ? 'Refreshing…' : 'Refresh'}</button>
      </header>
      {(invalidAddress || unavailable || error) && <p className="account-detail__refresh-error" role="status">Account refresh is currently unavailable.</p>}

      <div className="account-detail__overview">
        <section className="panel account-detail__summary-card" aria-labelledby="account-balance-title">
          <h2 id="account-balance-title">Balance</h2>
          {primary ? <><strong className="account-detail__main-balance">{primary.display_amount} {primary.symbol}</strong><dl className="account-detail__compact-list"><div><dt>Denom</dt><dd className="mono">{primary.denom}</dd></div><div><dt>Raw amount</dt><dd className="mono">{primary.amount}</dd></div><div><dt>Decimals</dt><dd className="mono">{primary.decimals}</dd></div></dl></> : <p className="account-detail__empty">No native bank balance</p>}
        </section>
        <section className="panel account-detail__summary-card" aria-labelledby="account-summary-title">
          <h2 id="account-summary-title">Account Summary</h2>
          <dl className="account-detail__compact-list"><div><dt>Account number</dt><dd className="mono">{account.account_number}</dd></div><div><dt>Sequence</dt><dd className="mono">{account.sequence}</dd></div><div><dt>Data source</dt><dd>Live RPC · {sourceLabel(account.source)}</dd></div></dl>
          <FetchedAt height={account.observed_height} />
        </section>
      </div>

      {balances.length > 1 && (
        <section className="panel account-detail__section" aria-labelledby="account-balances-title">
          <div className="panel__heading"><h2 id="account-balances-title">All Balances</h2></div>
          <div className="account-detail__balances">
            {balances.map((balance, index) => (
              <div className="account-detail__balance" key={`${balance.denom}-${index}`}>
                <strong>{balance.display_amount} {balance.symbol}</strong>
                <dl><div><dt>Denom</dt><dd className="mono">{balance.denom}</dd></div><div><dt>Raw amount</dt><dd className="mono">{balance.amount}</dd></div><div><dt>Decimals</dt><dd className="mono">{balance.decimals}</dd></div></dl>
              </div>
            ))}
          </div>
        </section>
      )}

      <details className="panel account-detail__details">
        <summary>Technical details</summary>
        <div className="account-detail__grid"><Field label="Chain ID" mono>{account.source?.chain_id || '—'}</Field>{account.public_key ? <><Field label="Public key type" mono>{account.public_key.type}</Field><div className="account-detail__field"><span className="account-detail__label">Public key value</span><CopyValue value={account.public_key.value} label="public key" /></div></> : <p className="account-detail__empty">Public key not available</p>}</div>
      </details>

      {account.validator_relation && (
        <section className="panel account-detail__compact-card account-detail__validator" aria-labelledby="account-validator-title">
          <h2 id="account-validator-title">Validator</h2>
          <Field label="Validator">{account.validator_relation.moniker || '—'}</Field><div className="account-detail__field"><span className="account-detail__label">Operator account</span><CopyValue value={account.validator_relation.operator_address} label="operator account" href={`/accounts/${encodeURIComponent(account.validator_relation.operator_address)}`} /></div><div className="account-detail__field"><span className="account-detail__label">Signing validator</span><CopyValue value={account.validator_relation.signing_address} label="signing validator" href={`/validators/${encodeURIComponent(account.validator_relation.signing_address)}`} /></div>
        </section>
      )}
    </article>
  )
}
