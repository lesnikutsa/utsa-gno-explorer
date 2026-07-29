import { CopyButton } from '../components/CopyButton'

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

function StatePanel({ title, message, retry }) {
  return (
    <section className="panel account-detail__state" role="status" aria-live="polite">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
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

function SourceFields({ account }) {
  return (
    <>
      <Field label="Observed Height" mono>{present(account.observed_height) ? <a href={`/blocks/${encodeURIComponent(account.observed_height)}`}>#{account.observed_height}</a> : '—'}</Field>
      <Field label="Chain ID" mono>{present(account.source?.chain_id) ? account.source.chain_id : '—'}</Field>
      <Field label="Data Source">Live RPC ({sourceLabel(account.source)})</Field>
    </>
  )
}

function MissingAccount({ account }) {
  return (
    <article className="account-detail" aria-labelledby="account-detail-title">
      <a className="account-detail__back" href="/">← Back to Overview</a>
      <header className="account-detail__header"><h1 id="account-detail-title">Account not found</h1></header>
      <p className="account-detail__message">This address has no account state on the current network.</p>
      <section className="panel account-detail__section" aria-labelledby="account-request-title">
        <div className="panel__heading"><h2 id="account-request-title">Requested Account</h2></div>
        <div className="account-detail__grid">
          <div className="account-detail__field"><span className="account-detail__label">Requested Address</span><CopyValue value={account.address} label="account address" /></div>
          <SourceFields account={account} />
        </div>
      </section>
    </article>
  )
}

export function AccountDetail({ accountDetail }) {
  const { account, loading, invalidAddress, unavailable, error, retry } = accountDetail

  if (loading && !account) return <StatePanel title="Loading account…" />
  if (invalidAddress && !account) return <StatePanel title="Invalid account address" message="The requested account address is not valid for this network." />
  if (unavailable && !account) return <StatePanel title="Account data is temporarily unavailable" message="The Explorer could not read current account state from a fresh RPC endpoint." retry={retry} />
  if (error && !account) return <StatePanel title="Account details are currently unavailable" retry={retry} />
  if (!account?.found) return <MissingAccount account={account} />

  const balances = Array.isArray(account.balances) ? account.balances : []
  const primary = balances.find((balance) => balance.symbol === 'GNOT')

  return (
    <article className="account-detail" aria-labelledby="account-detail-title">
      <a className="account-detail__back" href="/">← Back to Overview</a>
      <header className="account-detail__header">
        <div><h1 id="account-detail-title">Account</h1><CopyValue value={account.address} label="account address" /></div>
        <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading} aria-label="Refresh account details">{loading ? 'Refreshing…' : 'Refresh'}</button>
      </header>
      {(invalidAddress || unavailable || error) && <p className="account-detail__refresh-error" role="status">Account refresh is currently unavailable.</p>}

      <section className="panel account-detail__section" aria-labelledby="account-balance-title">
        <div className="panel__heading"><h2 id="account-balance-title">Balance</h2></div>
        {primary && <div className="account-detail__primary-balance"><strong>{primary.display_amount} {primary.symbol}</strong><span>{primary.denom}</span></div>}
        {balances.length === 0 ? <p className="account-detail__empty">No native bank balances</p> : (
          <div className="account-detail__balances">
            {balances.map((balance, index) => (
              <div className="account-detail__balance" key={`${balance.denom}-${index}`}>
                <strong>{balance.display_amount} {balance.symbol}</strong>
                <dl><div><dt>Denom</dt><dd className="mono">{balance.denom}</dd></div><div><dt>Raw amount</dt><dd className="mono">{balance.amount}</dd></div><div><dt>Decimals</dt><dd className="mono">{balance.decimals}</dd></div></dl>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel account-detail__section" aria-labelledby="account-metadata-title">
        <div className="panel__heading"><h2 id="account-metadata-title">Account Details</h2></div>
        <div className="account-detail__grid"><Field label="Account Number" mono>{account.account_number}</Field><Field label="Sequence" mono>{account.sequence}</Field><SourceFields account={account} /></div>
      </section>

      <section className="panel account-detail__section" aria-labelledby="account-public-key-title">
        <div className="panel__heading"><h2 id="account-public-key-title">Public Key</h2></div>
        {account.public_key ? <div className="account-detail__grid"><Field label="Type" mono>{account.public_key.type}</Field><div className="account-detail__field"><span className="account-detail__label">Value</span><CopyValue value={account.public_key.value} label="public key" /></div></div> : <p className="account-detail__empty">Public key not available</p>}
      </section>

      {account.validator_relation && (
        <section className="panel account-detail__section" aria-labelledby="account-validator-title">
          <div className="panel__heading"><h2 id="account-validator-title">Validator Relation</h2></div>
          <div className="account-detail__grid"><Field label="Moniker">{account.validator_relation.moniker || '—'}</Field><div className="account-detail__field"><span className="account-detail__label">Operator Address</span><CopyValue value={account.validator_relation.operator_address} label="operator address" /></div><div className="account-detail__field"><span className="account-detail__label">Signing Address</span><CopyValue value={account.validator_relation.signing_address} label="signing address" href={`/validators/${encodeURIComponent(account.validator_relation.signing_address)}`} /></div></div>
        </section>
      )}
    </article>
  )
}
