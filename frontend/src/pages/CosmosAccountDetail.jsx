import { CopyButton } from '../components/CopyButton'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { formatTokenAmount } from '../utils/cosmosFormat'
import '../styles/cosmos-account-detail.css'

const assetFor = (network, denom) => network.assets?.find((asset) => asset.base === denom) || null
const coinFor = (coins, denom) => (coins || []).find((coin) => coin.denom === denom) || null
const hasAmount = (coin) => coin && !/^0(?:\.0+)?$/.test(String(coin.amount))

function formatCoin(coin, network) {
  if (!coin) return '—'
  const asset = assetFor(network, coin.denom)
  return asset ? formatTokenAmount(String(coin.amount), asset.exponent, asset.symbol) : `${coin.amount} ${coin.denom}`
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return 'Complete'
  let value = Math.floor(Number(seconds))
  const days = Math.floor(value / 86400); value %= 86400
  const hours = Math.floor(value / 3600); value %= 3600
  const minutes = Math.floor(value / 60)
  if (days) return `${days}d ${hours}h`
  if (hours) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function utc(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })
}

function AddressValue({ value, label }) {
  return <span className="cosmos-account-address-value"><code>{value}</code><CopyButton value={value} label={label} showTitle={false} /></span>
}

function ValidatorName({ network, validator }) {
  return <span className="cosmos-account-validator">
    <a href={`/networks/${network.id}/validators/${validator.operator_address}`} className="accent-value">{validator.moniker || 'Validator'}</a>
    <code title={validator.operator_address}>{validator.operator_address}</code>
  </span>
}

function CoinStack({ coins, network }) {
  const visible = (coins || []).filter(hasAmount)
  return visible.length ? <span className="cosmos-account-coin-stack">{visible.map((coin) => <span key={coin.denom}>{formatCoin(coin, network)}</span>)}</span> : '—'
}

function SummaryCard({ label, children, meta }) {
  return <article className="card status-card cosmos-account-summary-card"><span>{label}</span><strong>{children}</strong>{meta && <small>{meta}</small>}</article>
}

function StateHint({ state, children }) {
  return state === 'available' ? children : <p className="muted cosmos-account-unavailable">Temporarily unavailable from the current API.</p>
}

export function CosmosAccountDetail({ network, address }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/accounts/${encodeURIComponent(address)}`, 15000)
  if (!resource.data && resource.loading) return <section className="cosmos-account-detail"><p>Loading account…</p></section>
  if (!resource.data) return <section className="cosmos-account-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}`}>← Back to Overview</a><p className="cosmos-error">Account data is temporarily unavailable or the address is invalid.</p></section>

  const account = resource.data
  const configuredAssets = network.assets || []
  const headlineAssets = configuredAssets.slice(0, 2)
  const primaryAsset = configuredAssets[0]
  const bankAvailable = account.states.bank === 'available'
  const stakingAvailable = account.states.staking === 'available'
  const rewardsAvailable = account.states.rewards === 'available'
  const delegatedCoin = coinFor(account.delegated_total, account.bond_denom) || account.delegated_total?.[0] || null
  const rewardHeadline = (primaryAsset && coinFor(account.rewards_total, primaryAsset.base)) || account.rewards_total?.find(hasAmount) || null
  const otherRewardCount = (account.rewards_total || []).filter((coin) => coin.denom !== rewardHeadline?.denom && hasAmount(coin)).length
  const delegationCount = account.delegations?.length || 0
  const unbondingCount = (account.unbonding || []).reduce((sum, group) => sum + (group.entries?.length || 0), 0)

  return <section className="cosmos-account-detail theme-compatible">
    <a className="cosmos-back block-detail__back" href={`/networks/${network.id}`}>← Back to Overview</a>

    <header className="panel cosmos-account-hero">
      <div className="cosmos-account-hero__title"><div><span className="cosmos-account-eyebrow">Account</span><h1>{network.presentation?.projectName || network.id}</h1></div>{account.validator_relation && <a className="cosmos-account-validator-link" href={`/networks/${network.id}/validators/${account.validator_relation.operator_address}`}>Validator account · {account.validator_relation.moniker || 'Open validator'} →</a>}</div>
      <AddressValue value={account.address} label="account address" />
      {!account.exists && <p className="muted cosmos-account-empty-note">No current account state was found in the available live modules.</p>}
      <div className="cosmos-account-summary-grid">
        {headlineAssets.map((asset) => <SummaryCard key={asset.base} label={`${asset.symbol} Balance`}>{bankAvailable ? formatTokenAmount(String(coinFor(account.balances, asset.base)?.amount || '0'), asset.exponent, asset.symbol) : '—'}</SummaryCard>)}
        <SummaryCard label="Delegated" meta={stakingAvailable ? `${delegationCount} validator${delegationCount === 1 ? '' : 's'}` : 'Unavailable'}>{stakingAvailable ? (delegatedCoin ? formatCoin(delegatedCoin, network) : primaryAsset ? formatTokenAmount('0', primaryAsset.exponent, primaryAsset.symbol) : '0') : '—'}</SummaryCard>
        <SummaryCard label="Rewards" meta={!rewardsAvailable ? 'Unavailable' : otherRewardCount ? `+${otherRewardCount} other asset${otherRewardCount === 1 ? '' : 's'}` : null}>{rewardsAvailable ? (rewardHeadline ? formatCoin(rewardHeadline, network) : primaryAsset ? formatTokenAmount('0', primaryAsset.exponent, primaryAsset.symbol) : '0') : '—'}</SummaryCard>
      </div>
    </header>

    <div className="cosmos-account-primary-grid">
      <section className="panel cosmos-account-panel">
        <div className="panel__heading"><div><h2>Balances</h2><span className="panel__meta">Current bank balances</span></div></div>
        <StateHint state={account.states.bank}>{<div className="cosmos-account-balance-list">
          {configuredAssets.map((asset) => <div className="cosmos-account-balance-row" key={asset.base}><span><strong>{asset.symbol}</strong><code>{asset.base}</code></span><strong>{formatTokenAmount(String(coinFor(account.balances, asset.base)?.amount || '0'), asset.exponent, asset.symbol)}</strong></div>)}
          {(account.balances || []).filter((coin) => !assetFor(network, coin.denom)).map((coin) => <div className="cosmos-account-balance-row" key={coin.denom}><span><strong>{coin.denom}</strong><code>unregistered denom</code></span><strong>{formatCoin(coin, network)}</strong></div>)}
        </div>}</StateHint>
        {account.balances_truncated && <p className="muted cosmos-account-footnote">Additional bank denoms exist beyond the bounded live page.</p>}
      </section>

      <section className="panel cosmos-account-panel cosmos-account-info">
        <div className="panel__heading"><div><h2>Account Information</h2><span className="panel__meta">Current x/auth state</span></div></div>
        <dl><div><dt>Account number</dt><dd>{account.account_number ?? '—'}</dd></div><div><dt>Sequence</dt><dd>{account.sequence ?? '—'}</dd></div><div><dt>Delegations</dt><dd>{stakingAvailable ? delegationCount : '—'}</dd></div><div><dt>Unbonding entries</dt><dd>{account.states.unbonding === 'available' ? unbondingCount : '—'}</dd></div></dl>
      </section>
    </div>

    <section className="panel cosmos-account-panel cosmos-account-delegations">
      <div className="panel__heading"><div><h2>Delegations</h2><span className="panel__meta">Current staking positions</span></div><div className="cosmos-account-panel-total">{stakingAvailable ? (delegatedCoin ? formatCoin(delegatedCoin, network) : '0') : '—'}</div></div>
      <StateHint state={account.states.staking}>{account.delegations?.length ? <div className="cosmos-account-table-wrap"><table><thead><tr><th>Validator</th><th>Status</th><th>Delegated</th><th>Rewards</th></tr></thead><tbody>{account.delegations.map((row) => <tr key={row.validator.operator_address}><td><ValidatorName network={network} validator={row.validator} /></td><td><span className={`cosmos-account-status is-${row.validator.category || 'unknown'}`}>{row.validator.category || 'Unknown'}</span></td><td><strong>{formatCoin(row.balance, network)}</strong></td><td><CoinStack coins={row.rewards} network={network} /></td></tr>)}</tbody></table></div> : <p className="muted">No active delegations.</p>}</StateHint>
      {account.delegations_truncated && <p className="muted cosmos-account-footnote">Additional delegations exist beyond the bounded live page.</p>}
    </section>

    <section className="panel cosmos-account-panel cosmos-account-unbonding">
      <div className="panel__heading"><div><h2>Unbonding</h2><span className="panel__meta">Tokens currently leaving staking</span></div></div>
      <StateHint state={account.states.unbonding}>{account.unbonding?.length ? <div className="cosmos-account-unbonding-list">{account.unbonding.flatMap((group) => group.entries.map((entry, index) => <article className="cosmos-account-unbonding-row" key={`${group.validator.operator_address}:${entry.creation_height}:${index}`}><ValidatorName network={network} validator={group.validator} /><div><span>Amount</span><strong>{group.denom ? formatCoin({ denom: group.denom, amount: entry.balance }, network) : entry.balance}</strong></div><div><span>Completion</span><strong>{utc(entry.completion_time)}</strong></div><div><span>Remaining</span><strong>{formatDuration(entry.remaining_seconds)}</strong></div></article>))}</div> : <p className="muted">No active unbonding delegations.</p>}</StateHint>
      {account.unbonding_truncated && <p className="muted cosmos-account-footnote">Additional unbonding entries exist beyond the bounded live page.</p>}
    </section>

    <div className="cosmos-account-secondary-grid">
      <section className="panel cosmos-account-panel cosmos-account-rewards">
        <div className="panel__heading"><div><h2>Rewards</h2><span className="panel__meta">Claimable staking rewards</span></div></div>
        <StateHint state={account.states.rewards}>{account.rewards_total?.some(hasAmount) ? <>
          <div className="cosmos-account-reward-total">{account.rewards_total.filter(hasAmount).map((coin) => <div key={coin.denom}><span>{assetFor(network, coin.denom)?.symbol || coin.denom}</span><strong>{formatCoin(coin, network)}</strong></div>)}</div>
          {account.rewards_by_validator?.length > 0 && <div className="cosmos-account-reward-breakdown">{account.rewards_by_validator.map((row) => <div key={row.validator.operator_address}><ValidatorName network={network} validator={row.validator} /><CoinStack coins={row.rewards} network={network} /></div>)}</div>}
        </> : <p className="muted">No claimable rewards.</p>}</StateHint>
      </section>

      <details className="panel cosmos-account-panel cosmos-account-technical">
        <summary>Technical details</summary>
        <dl><div><dt>Account type</dt><dd><code>{account.account_type || '—'}</code></dd></div><div><dt>Bond denom</dt><dd><code>{account.bond_denom || '—'}</code></dd></div><div><dt>Withdraw address</dt><dd>{account.withdraw_address ? <AddressValue value={account.withdraw_address} label="withdraw address" /> : '—'}</dd></div><div><dt>Public key type</dt><dd><code>{account.public_key?.type || '—'}</code></dd></div>{account.public_key?.value && <div><dt>Public key</dt><dd><AddressValue value={account.public_key.value} label="public key" /></dd></div>}</dl>
      </details>
    </div>
  </section>
}
