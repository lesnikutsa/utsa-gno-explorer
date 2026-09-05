import { CopyButton } from '../components/CopyButton'
import { CosmosAccountActivity } from '../components/CosmosAccountActivity'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { formatTokenAmount } from '../utils/cosmosFormat'
import '../styles/cosmos-account-detail.css'

const assetFor = (network, denom) => network.assets?.find((asset) => asset.base === denom) || null
const coinFor = (coins, denom) => (coins || []).find((coin) => coin.denom === denom) || null
const hasAmount = (coin) => coin && !/^0(?:\.0+)?$/.test(String(coin.amount))

function formatCoin(coin, network) {
  if (!coin) return '—'
  const asset = assetFor(network, coin.denom)
  if (!asset) return `${coin.amount} ${coin.denom}`
  const formatted = formatTokenAmount(String(coin.amount), asset.exponent, asset.symbol)
  if (hasAmount(coin) && formatted === `0 ${asset.symbol}`) return `<0.000001 ${asset.symbol}`
  return formatted
}

function approximateUsd(coin, network, market) {
  const nativeDenom = network.presentation?.nativeDenom || network.assets?.[0]?.base
  const marketAsset = network.assets?.find((asset) => asset.base === nativeDenom) || network.assets?.[0]
  const price = Number(market?.price)
  const amount = Number(coin?.amount)
  const exponent = marketAsset?.exponent
  if (!marketAsset || coin?.denom !== marketAsset.base || !Number.isFinite(price) || price <= 0 || !Number.isFinite(amount) || amount < 0 || !Number.isInteger(exponent) || exponent < 0 || exponent > 30) return null
  const usd = amount / (10 ** exponent) * price
  if (!Number.isFinite(usd) || usd <= 0) return null
  if (usd >= 1000) return `$${usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (usd >= 1) return `$${usd.toFixed(2)}`
  const digits = usd >= 0.01 ? 4 : 8
  return `$${usd.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '')}`
}

function sumUnbonding(groups) {
  try {
    let total = 0n
    for (const group of groups || []) {
      for (const entry of group.entries || []) {
        if (!/^\d+$/.test(String(entry.balance))) return null
        total += BigInt(entry.balance)
      }
    }
    return total.toString()
  } catch {
    return null
  }
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
  return <div className="cosmos-account-validator-cell">
    <CosmosValidatorIdentity
      moniker={validator.moniker || 'Validator'}
      address={validator.operator_address}
      imageSrc={validator.avatar_url}
      showTitles={false}
      fullAddress
      href={`/networks/${network.id}/validators/${encodeURIComponent(validator.operator_address)}`}
    />
  </div>
}

function CoinStack({ coins, network, market }) {
  const visible = (coins || []).filter(hasAmount)
  return visible.length ? <span className="cosmos-account-coin-stack">{visible.map((coin) => {
    const usd = approximateUsd(coin, network, market)
    return <span className="cosmos-account-coin-line" key={coin.denom}>
      <span>{formatCoin(coin, network)}</span>
      {usd && <small className="cosmos-account-reward-usd">≈ {usd}</small>}
    </span>
  })}</span> : '—'
}

function buildDelegationRows(delegations, rewardsByValidator, bondDenom) {
  const rewardsByOperator = new Map((rewardsByValidator || []).map((row) => [row.validator.operator_address, row]))
  const seen = new Set()
  const rows = []

  for (const delegation of delegations || []) {
    const operator = delegation.validator.operator_address
    const rewardRow = rewardsByOperator.get(operator)
    const rewards = rewardRow?.rewards || delegation.rewards || []
    if (hasAmount(delegation.balance) || rewards.some(hasAmount)) rows.push({ ...delegation, rewards })
    seen.add(operator)
  }

  for (const rewardRow of rewardsByValidator || []) {
    const operator = rewardRow.validator.operator_address
    if (seen.has(operator) || !(rewardRow.rewards || []).some(hasAmount)) continue
    rows.push({
      validator: rewardRow.validator,
      shares: '0',
      balance: bondDenom ? { denom: bondDenom, amount: '0' } : null,
      rewards: rewardRow.rewards || [],
    })
  }

  return rows
}

function SummaryCard({ label, children, usd, meta }) {
  return <article className="card status-card cosmos-validator-summary__card cosmos-account-summary-card">
    <span>{label}</span>
    <strong>{children}</strong>
    {usd && <small className="cosmos-account-usd">≈ {usd}</small>}
    {meta && <small className="cosmos-account-summary-card__meta">{meta}</small>}
  </article>
}

function WalletAsset({ coin, network, market }) {
  const usd = approximateUsd(coin, network, market)
  return <article className="cosmos-account-wallet-asset">
    <span>{assetFor(network, coin.denom)?.symbol || coin.denom}</span>
    <strong>{formatCoin(coin, network)}</strong>
    {usd && <small className="cosmos-account-usd">≈ {usd}</small>}
  </article>
}

function StateHint({ state, children }) {
  return state === 'available' ? children : <p className="muted cosmos-account-unavailable">Temporarily unavailable from the current API.</p>
}

export function CosmosAccountDetail({ network, address }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/accounts/${encodeURIComponent(address)}`, 15000)
  const market = useCosmosResource(`/api/networks/${network.id}/market`, 30000)
  if (!resource.data && resource.loading) return <section className="cosmos-account-detail"><p>Loading account…</p></section>
  if (!resource.data) return <section className="cosmos-account-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}`}>← Back to Overview</a><p className="cosmos-error">Account data is temporarily unavailable or the address is invalid.</p></section>

  const account = resource.data
  const configuredAssets = network.assets || []
  const primaryDenom = network.presentation?.nativeDenom || configuredAssets[0]?.base || account.bond_denom
  const primaryAsset = assetFor(network, primaryDenom) || configuredAssets[0] || null
  const bankAvailable = account.states.bank === 'available'
  const stakingAvailable = account.states.staking === 'available'
  const rewardsAvailable = account.states.rewards === 'available'
  const unbondingAvailable = account.states.unbonding === 'available'
  const activeDelegations = (account.delegations || []).filter((row) => hasAmount(row.balance))
  const delegationRows = buildDelegationRows(account.delegations, account.rewards_by_validator, account.bond_denom)
  const delegationSurfaceAvailable = stakingAvailable || rewardsAvailable
  const delegatedCoin = coinFor(account.delegated_total, account.bond_denom) || account.delegated_total?.[0] || null
  const visibleRewards = (account.rewards_total || []).filter(hasAmount)
  const rewardHeadline = coinFor(visibleRewards, primaryDenom) || visibleRewards[0] || null
  const otherRewardCount = visibleRewards.filter((coin) => coin.denom !== rewardHeadline?.denom).length
  const configuredDenoms = new Set(configuredAssets.map((asset) => asset.base))
  const balanceCoins = [
    ...configuredAssets.map((asset) => coinFor(account.balances, asset.base) || { denom: asset.base, amount: '0' }),
    ...(account.balances || []).filter((coin) => !configuredDenoms.has(coin.denom) && hasAmount(coin)),
  ]
  const primaryBalance = primaryDenom ? coinFor(account.balances, primaryDenom) || { denom: primaryDenom, amount: '0' } : null
  const delegationCount = activeDelegations.length
  const unbondingCount = (account.unbonding || []).reduce((sum, group) => sum + (group.entries?.length || 0), 0)
  const unbondingAmount = sumUnbonding(account.unbonding)
  const unbondingCoin = account.bond_denom && unbondingAmount != null ? { denom: account.bond_denom, amount: unbondingAmount } : null
  const balanceUsd = bankAvailable ? approximateUsd(primaryBalance, network, market.data) : null
  const delegatedUsd = stakingAvailable ? approximateUsd(delegatedCoin, network, market.data) : null
  const rewardsUsd = rewardsAvailable ? approximateUsd(rewardHeadline, network, market.data) : null
  const unbondingUsd = unbondingAvailable ? approximateUsd(unbondingCoin, network, market.data) : null

  return <section className="cosmos-account-detail theme-compatible">
    <a className="cosmos-back block-detail__back" href={`/networks/${network.id}`}>← Back to Overview</a>

    <header className="panel cosmos-account-hero">
      <div className="cosmos-account-hero__profile">
        <div className="cosmos-account-hero__main">
          <span className="cosmos-account-network-logo" aria-hidden="true"><img src={network.presentation?.networkIconSrc} alt="" /></span>
          <div className="cosmos-account-hero__identity">
            <h1>Account</h1>
            <div className="cosmos-account-identity-line">
              <AddressValue value={account.address} label="account address" />
              {account.validator_relation && <p className="cosmos-account-validator-relation">This account belongs to validator <a href={`/networks/${network.id}/validators/${account.validator_relation.operator_address}`}>{account.validator_relation.moniker || 'Unknown validator'}</a></p>}
            </div>
          </div>
        </div>
      </div>
      {!account.exists && <p className="muted cosmos-account-empty-note">No current account state was found in the available live modules.</p>}
      <div className="cosmos-validator-hero__metrics cosmos-account-summary-grid">
        <SummaryCard label="Balance" usd={balanceUsd}>{bankAvailable ? (primaryBalance ? formatCoin(primaryBalance, network) : primaryAsset ? formatTokenAmount('0', primaryAsset.exponent, primaryAsset.symbol) : '0') : '—'}</SummaryCard>
        <SummaryCard label="Delegated" usd={delegatedUsd} meta={stakingAvailable ? `${delegationCount} current delegation${delegationCount === 1 ? '' : 's'}` : 'Unavailable'}>{stakingAvailable ? (delegatedCoin ? formatCoin(delegatedCoin, network) : primaryAsset ? formatTokenAmount('0', primaryAsset.exponent, primaryAsset.symbol) : '0') : '—'}</SummaryCard>
        <SummaryCard label="Rewards" usd={rewardsUsd} meta={!rewardsAvailable ? 'Unavailable' : otherRewardCount ? `+${otherRewardCount} other asset${otherRewardCount === 1 ? '' : 's'}` : 'Claimable now'}>{rewardsAvailable ? (rewardHeadline ? formatCoin(rewardHeadline, network) : primaryAsset ? formatTokenAmount('0', primaryAsset.exponent, primaryAsset.symbol) : '0') : '—'}</SummaryCard>
        <SummaryCard label="Unbonding" usd={unbondingUsd} meta={!unbondingAvailable ? 'Unavailable' : unbondingCount ? `${unbondingCount} active entr${unbondingCount === 1 ? 'y' : 'ies'}` : 'No active entries'}>{unbondingAvailable ? (unbondingCoin ? formatCoin(unbondingCoin, network) : primaryAsset ? formatTokenAmount('0', primaryAsset.exponent, primaryAsset.symbol) : '0') : '—'}</SummaryCard>
      </div>
      <div className="cosmos-account-hero__wallet-assets">
        <span className="cosmos-account-hero__wallet-assets-label">Wallet assets</span>
        {bankAvailable ? <div className="cosmos-account-wallet-assets-grid">{balanceCoins.map((coin) => <WalletAsset key={coin.denom} coin={coin} network={network} market={market.data} />)}</div> : <span className="muted cosmos-account-wallet-assets-unavailable">Temporarily unavailable from the current API.</span>}
      </div>
    </header>

    <section className="panel cosmos-account-panel cosmos-account-delegations">
      <div className="panel__heading"><h2>Delegations</h2><div className="cosmos-account-panel-total">{stakingAvailable ? (delegatedCoin ? formatCoin(delegatedCoin, network) : '0') : '—'}</div></div>
      {delegationSurfaceAvailable ? delegationRows.length ? <div className="cosmos-account-table-wrap"><table><thead><tr><th>Validator</th><th>Status</th><th>Delegated</th><th>Rewards</th></tr></thead><tbody>{delegationRows.map((row) => <tr key={row.validator.operator_address}><td><ValidatorName network={network} validator={row.validator} /></td><td><span className={`cosmos-account-status is-${row.validator.category || 'unknown'}`}>{row.validator.category || 'Unknown'}</span></td><td><strong>{stakingAvailable ? formatCoin(row.balance, network) : '—'}</strong></td><td>{rewardsAvailable ? <CoinStack coins={row.rewards} network={network} market={market.data} /> : '—'}</td></tr>)}</tbody></table></div> : <p className="muted cosmos-account-empty-state">No delegations or claimable rewards.</p> : <p className="muted cosmos-account-unavailable">Temporarily unavailable from the current API.</p>}
      {account.delegations_truncated && <p className="muted cosmos-account-footnote">Additional delegation records exist beyond the bounded live page.</p>}
    </section>

    <section className="panel cosmos-account-panel cosmos-account-unbonding">
      <div className="panel__heading"><h2>Unbonding</h2></div>
      <StateHint state={account.states.unbonding}>{account.unbonding?.length ? <div className="cosmos-account-unbonding-list"><div className="cosmos-account-unbonding-row" aria-hidden="true"><div><span>Validator</span></div><div><span>Amount</span></div><div><span>Completion</span></div><div><span>Remaining</span></div></div>{account.unbonding.flatMap((group) => group.entries.map((entry, index) => <article className="cosmos-account-unbonding-row" key={`${group.validator.operator_address}:${entry.creation_height}:${index}`}><ValidatorName network={network} validator={group.validator} /><div><strong>{group.denom ? formatCoin({ denom: group.denom, amount: entry.balance }, network) : entry.balance}</strong></div><div><strong>{utc(entry.completion_time)}</strong></div><div><strong>{formatDuration(entry.remaining_seconds)}</strong></div></article>))}</div> : <p className="muted cosmos-account-empty-state">No active unbonding delegations.</p>}</StateHint>
      {account.unbonding_truncated && <p className="muted cosmos-account-footnote">Additional unbonding entries exist beyond the bounded live page.</p>}
    </section>

    <CosmosAccountActivity network={network} address={account.address} market={market.data} />

    <details className="panel cosmos-account-panel cosmos-account-technical">
      <summary>Technical details</summary>
      <dl>
        <div><dt>Account number</dt><dd>{account.account_number ?? '—'}</dd></div>
        <div><dt>Sequence</dt><dd>{account.sequence ?? '—'}</dd></div>
        <div><dt>Active delegations</dt><dd>{stakingAvailable ? delegationCount : '—'}</dd></div>
        <div><dt>Unbonding entries</dt><dd>{unbondingAvailable ? unbondingCount : '—'}</dd></div>
        <div><dt>Account type</dt><dd><code>{account.account_type || '—'}</code></dd></div>
        <div><dt>Bond denom</dt><dd><code>{account.bond_denom || '—'}</code></dd></div>
        <div><dt>Withdraw address</dt><dd>{account.withdraw_address ? <AddressValue value={account.withdraw_address} label="withdraw address" /> : '—'}</dd></div>
        <div><dt>Public key type</dt><dd><code>{account.public_key?.type || '—'}</code></dd></div>
        {account.public_key?.value && <div><dt>Public key</dt><dd><AddressValue value={account.public_key.value} label="public key" /></dd></div>}
      </dl>
    </details>
  </section>
}
