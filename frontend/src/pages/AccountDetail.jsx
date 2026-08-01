import { CopyButton } from '../components/CopyButton'
import { TransactionTypeBadge } from '../components/TransactionTypeBadge'
import { TransactionExecutionBadge } from '../components/TransactionExecutionBadge'
import { networkProfile } from '../config/networkProfile'
import { findNativeBalance, findOtherBalances, formatAmountString, getAccountDetailView } from '../utils/account'

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

function TechnicalField({ label, children, mono = false }) {
  return <div className="account-detail__technical-field"><span>{label}</span><strong className={mono ? 'mono' : ''}>{children}</strong></div>
}

function Skeleton({ className = '' }) {
  return <span className={`account-detail__placeholder ${className}`.trim()} aria-hidden="true" />
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

function AccountTransactions({ address, history, retry, loadMore }) {
  return (
    <section className="panel account-detail__transactions" aria-labelledby="account-transactions-title">
      <h2 id="account-transactions-title">Transactions</h2>
      {history.loading && <div className="account-detail__skeleton" aria-label="Loading transaction history"><span /><span /><span /></div>}
      {!history.loading && history.items.length === 0 && !history.initialError && <p>No indexed transactions found for this account.</p>}
      {history.items.length > 0 && <div className="account-detail__transaction-list">
        <div className="account-detail__transaction-header" aria-hidden="true"><span>Type</span><span>Direction</span><span>Account</span><span>Amount</span><span>Block</span><span>TX Hash</span><span>Status</span></div>
        {history.items.map((item) => {
        const counterpartyValid = item.counterparty && item.counterparty !== address && /^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$/.test(item.counterparty)
        const direction = item.direction === 'outgoing' ? 'Outgoing' : item.direction === 'incoming' ? 'Incoming' : 'Self'
        return <article className="account-detail__transaction" key={`${item.block_height}:${item.index}`}>
          <div className="account-detail__transaction-operation" data-label="Type"><TransactionTypeBadge>{item.operation}</TransactionTypeBadge></div>
          <div className="account-detail__transaction-direction" data-label="Direction"><span className={`account-detail__direction account-detail__direction--${item.direction}`}>{direction}</span></div>
          <div className="account-detail__transaction-account" data-label="Account">{counterpartyValid ? <a className="account-detail__transaction-counterparty mono" href={`/accounts/${encodeURIComponent(item.counterparty)}`} title={item.counterparty}>{item.counterparty}</a> : '—'}</div>
          <span className="account-detail__transaction-amount" data-label="Amount">{item.amount != null ? String(item.amount) : '—'}</span>
          <div className="account-detail__transaction-block" data-label="Block"><a className="table-link" href={`/blocks/${item.block_height}`} aria-label={`Open block #${item.block_height}`}><span className="blocks-table__height accent-value mono">#{item.block_height.toLocaleString()}</span></a></div>
          <div className="account-detail__transaction-hash-cell" data-label="TX Hash"><a className="account-detail__transaction-hash mono" href={`/blocks/${item.block_height}/transactions/${item.index}`} title={item.tx_hash} aria-label={`Transaction hash ${item.tx_hash}`}>{item.tx_hash || '—'}</a></div>
          <div className="account-detail__transaction-status" data-label="Status"><TransactionExecutionBadge status={item.execution_status} /></div>
        </article>
      })}</div>}
      {history.initialError && <div role="status"><p>Transaction history is temporarily unavailable.</p><button className="blocks-page__button" type="button" onClick={retry}>Retry history</button></div>}
      {history.loadMoreError && <p role="status">Could not load more transactions. Retry with the same cursor.</p>}
      {history.pagination?.next_before_height && <button className="blocks-page__button" type="button" disabled={history.loadingMore} onClick={loadMore}>{history.loadingMore ? 'Loading…' : 'Load more'}</button>}
    </section>
  )
}

function MissingAccount({ account, retry, loading, refreshError, history, retryHistory, loadMoreHistory }) {
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
      </section>
      <AccountTransactions address={account.address} history={history} retry={retryHistory} loadMore={loadMoreHistory} />
    </article>
  )
}

export function AccountDetail({ accountDetail }) {
  const { account, requestedAddress, loading, invalidAddress, unavailable, error, retry, history, retryHistory, loadMoreHistory } = accountDetail
  const view = getAccountDetailView(accountDetail)

  if (view === 'invalid') return <StatePanel title="Invalid account address" message="The requested account address is not valid for this network." />
  if (view === 'unavailable') return <StatePanel title="Account data is temporarily unavailable" message="The Explorer could not read current account state from a fresh RPC endpoint." retry={retry} />
  if (view === 'error') return <StatePanel title="Account details are currently unavailable" retry={retry} />
  if (view === 'missing') return <MissingAccount account={account} retry={retry} loading={loading} refreshError={invalidAddress || unavailable || error} history={history} retryHistory={retryHistory} loadMoreHistory={loadMoreHistory} />

  const initialLoading = view === 'loading'
  const balances = Array.isArray(account?.balances) ? account.balances : []
  const primary = findNativeBalance(balances, networkProfile.nativeDenom)
  const otherBalances = findOtherBalances(balances, networkProfile.nativeDenom)

  return (
    <article className="account-detail" aria-labelledby="account-detail-title" aria-busy={loading ? 'true' : 'false'}>
      <a className="account-detail__back" href="/">← Back to Overview</a>
      <header className="account-detail__header">
        <div><h1 id="account-detail-title">Account</h1><CopyValue value={account?.address || requestedAddress} label="account address" /></div>
        <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading} aria-label="Refresh account details">{initialLoading ? 'Loading…' : loading ? 'Refreshing…' : 'Refresh'}</button>
      </header>
      {initialLoading && <p className="sr-only" role="status" aria-live="polite">Loading current account state…</p>}
      {loading && account?.found && <p className="account-detail__updating" role="status">Updating…</p>}
      {(invalidAddress || unavailable || error) && <p className="account-detail__refresh-error" role="status">Account refresh is currently unavailable.</p>}

      <div className="account-detail__overview">
        <section className="panel account-detail__summary-card" aria-labelledby="account-balance-title">
          <h2 id="account-balance-title">Account Balance</h2>
          {initialLoading ? <Skeleton className="account-detail__placeholder--balance" /> : primary ? <strong className="account-detail__main-balance">{formatAmountString(primary.display_amount)} {primary.symbol}</strong> : <p className="account-detail__empty">No native bank balance</p>}
        </section>
        <section className="panel account-detail__summary-card" aria-labelledby="account-summary-title">
          <h2 id="account-summary-title">Account Summary</h2>
          <dl className="account-detail__summary-values"><div><dt>Account number</dt><dd className="mono">{initialLoading ? <Skeleton /> : account.account_number}</dd></div><div><dt>Sequence</dt><dd className="mono">{initialLoading ? <Skeleton /> : account.sequence}</dd></div><div><dt>Denom</dt><dd className="mono">{initialLoading ? <Skeleton /> : primary?.denom || '—'}</dd></div><div><dt>Decimals</dt><dd className="mono">{initialLoading ? <Skeleton /> : present(primary?.decimals) ? primary.decimals : '—'}</dd></div><div className="account-detail__summary-raw"><dt>Raw amount</dt><dd className="mono">{initialLoading ? <Skeleton /> : primary?.amount || '—'}</dd></div></dl>
        </section>
      </div>

      {initialLoading ? <section className="panel account-detail__validator" aria-hidden="true"><Skeleton className="account-detail__placeholder--validator" /></section> : account.validator_relation && (
        <section className="panel account-detail__validator" aria-labelledby="account-validator-title">
          <h2 id="account-validator-title" className="sr-only">Validator relation</h2>
          <p>This account belongs to validator <a href={`/validators/${encodeURIComponent(account.validator_relation.signing_address)}`}>{account.validator_relation.moniker || 'Unknown validator'}</a></p>
        </section>
      )}

      {otherBalances.length > 0 && (
        <section className="panel account-detail__section" aria-labelledby="account-balances-title">
          <div className="panel__heading"><h2 id="account-balances-title">Other balances</h2></div>
          <div className="account-detail__balances">
            {otherBalances.map((balance, index) => (
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
        <div className="account-detail__technical-grid">
          <section aria-labelledby="account-network-details-title"><h3 id="account-network-details-title">Network</h3><div><TechnicalField label="Chain ID" mono>{initialLoading ? <Skeleton /> : account.source?.chain_id || '—'}</TechnicalField><TechnicalField label="RPC endpoint">{initialLoading ? <Skeleton /> : sourceLabel(account.source)}</TechnicalField><TechnicalField label="Observed RPC height" mono>{initialLoading ? <Skeleton /> : present(account.observed_height) ? <a href={`/blocks/${encodeURIComponent(account.observed_height)}`}>{account.observed_height}</a> : '—'}</TechnicalField></div></section>
          <section aria-labelledby="account-public-key-details-title"><h3 id="account-public-key-details-title">Public key</h3>{initialLoading ? <div><TechnicalField label="Public key type" mono><Skeleton /></TechnicalField><TechnicalField label="Public key value" mono><Skeleton /></TechnicalField></div> : account.public_key ? <div><TechnicalField label="Public key type" mono>{account.public_key.type}</TechnicalField><div className="account-detail__technical-field"><span>Public key value</span><CopyValue value={account.public_key.value} label="public key" /></div></div> : <p className="account-detail__empty">Public key not available</p>}</section>
        </div>
      </details>

      <AccountTransactions address={account?.address || requestedAddress} history={history} retry={retryHistory} loadMore={loadMoreHistory} />
    </article>
  )
}
