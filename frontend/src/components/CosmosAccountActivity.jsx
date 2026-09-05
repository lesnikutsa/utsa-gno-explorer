import { useEffect, useRef, useState } from 'react'
import { request } from '../services/api'
import { formatTokenAmount } from '../utils/cosmosFormat'
import '../styles/cosmos-account-activity.css'

const ACTION_LABELS = {
  received: 'Received',
  sent: 'Sent',
  self_transfer: 'Self transfer',
  delegate: 'Delegate',
  undelegate: 'Undelegate',
  redelegate: 'Redelegate',
  cancel_unbonding: 'Cancel unbonding',
  withdraw_reward: 'Withdraw reward',
  set_withdraw_address: 'Set withdraw address',
  fund_community_pool: 'Fund community pool',
  vote: 'Vote',
  deposit: 'Deposit',
  ibc_transfer: 'IBC transfer',
  ibc_received: 'IBC received',
  authz_execution: 'Authz execution',
  grant_authorization: 'Grant authorization',
  revoke_authorization: 'Revoke authorization',
  create_validator: 'Create validator',
  validator_operation: 'Validator operation',
  transaction: 'Transaction',
}

const assetFor = (network, denom) => network.assets?.find((asset) => asset.base === denom) || null

function actionTone(item) {
  if (!item.success) return 'failed'
  if (item.action === 'redelegate') return 'warning'
  if (item.action === 'withdraw_reward' || item.action === 'withdraw_commission') return 'neutral'
  return item.direction
}

function formatCoin(coin, network) {
  const asset = assetFor(network, coin?.denom)
  if (!coin) return '—'
  if (!asset) return `${coin.amount} ${coin.denom}`
  const formatted = formatTokenAmount(String(coin.amount), asset.exponent, asset.symbol)
  if (Number(coin.amount) > 0 && formatted === `0 ${asset.symbol}`) return `<0.000001 ${asset.symbol}`
  return formatted
}

function approximateUsd(coin, network, market) {
  const nativeDenom = network.presentation?.nativeDenom || network.assets?.[0]?.base
  const asset = assetFor(network, nativeDenom) || network.assets?.[0]
  const price = Number(market?.price)
  const amount = Number(coin?.amount)
  if (!asset || coin?.denom !== asset.base || !Number.isFinite(price) || price <= 0
      || !Number.isFinite(amount) || amount <= 0 || !Number.isInteger(asset.exponent)) return null
  const usd = amount / (10 ** asset.exponent) * price
  if (!Number.isFinite(usd) || usd <= 0) return null
  if (usd >= 1000) return `$${usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (usd >= 1) return `$${usd.toFixed(2)}`
  const digits = usd >= 0.01 ? 4 : 8
  return `$${usd.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '')}`
}

function utc(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })
}

function shorten(value, head = 12, tail = 8) {
  if (!value || value.length <= head + tail + 1) return value || '—'
  return `${value.slice(0, head)}…${value.slice(-tail)}`
}

function activityPath(networkId, address, page = 1) {
  const params = new URLSearchParams({ limit: '10', page: String(page) })
  return `/networks/${encodeURIComponent(networkId)}/accounts/${encodeURIComponent(address)}/activity?${params.toString()}`
}

function AmountDetail({ item, network, market }) {
  const prefix = item.direction === 'positive' ? '+' : item.direction === 'negative' ? '−' : ''
  const amounts = item.amounts || []
  return <div className="cosmos-account-activity__amount-detail">
    {amounts.length ? amounts.map((coin, index) => {
      const usd = approximateUsd(coin, network, market)
      return <span className="cosmos-account-activity__coin" key={`${coin.denom}:${index}`}>
        <span>{prefix}{formatCoin(coin, network)}</span>
        {usd && <small>≈ {usd}</small>}
      </span>
    }) : <span>—</span>}
    {item.detail && <small className="cosmos-account-activity__detail" title={item.detail}>{shorten(item.detail, 26, 12)}</small>}
  </div>
}

export function CosmosAccountActivity({ network, address, market }) {
  const [state, setState] = useState({ status: 'loading', items: [], page: 1, hasMore: false, loadingMore: false })
  const scope = useRef({ generation: 0, controller: null })

  useEffect(() => {
    scope.current.controller?.abort()
    const controller = new AbortController()
    const generation = scope.current.generation + 1
    scope.current = { generation, controller }
    const isCurrent = () => scope.current.generation === generation && scope.current.controller === controller
    setState({ status: 'loading', items: [], page: 1, hasMore: false, loadingMore: false })
    request(activityPath(network.id, address), { signal: controller.signal })
      .then((data) => {
        if (isCurrent()) setState({ status: data.state, items: data.items || [], page: 1, hasMore: data.has_more === true, loadingMore: false })
      })
      .catch((error) => {
        if (error?.name !== 'AbortError' && isCurrent()) setState({ status: 'error', items: [], page: 1, hasMore: false, loadingMore: false })
      })
    return () => controller.abort()
  }, [network.id, address])

  const showMore = () => {
    if (state.loadingMore || !state.hasMore || state.page >= 5) return
    const page = state.page + 1
    setState((current) => ({ ...current, loadingMore: true }))
    request(activityPath(network.id, address, page))
      .then((data) => setState((current) => ({
        status: current.status === 'partial' || data.state === 'partial' ? 'partial' : data.state,
        items: [...current.items, ...(data.items || [])].filter((item, index, rows) => rows.findIndex((candidate) => candidate.tx_hash === item.tx_hash) === index),
        page,
        hasMore: data.has_more === true,
        loadingMore: false,
      })))
      .catch(() => setState((current) => ({ ...current, loadingMore: false })))
  }

  return <section className="panel cosmos-account-panel cosmos-account-activity">
    <div className="panel__heading"><h2>Recent Activity</h2></div>
    {state.status === 'loading' ? <p className="muted cosmos-account-activity__state">Loading recent activity…</p>
      : state.status === 'indexing_unavailable' ? <p className="muted cosmos-account-activity__state">Recent activity is unavailable from the current transaction index.</p>
        : state.status === 'error' ? <p className="muted cosmos-account-activity__state">Recent activity is temporarily unavailable.</p>
          : !state.items.length ? <p className="muted cosmos-account-activity__state">No recent account activity found.</p>
            : <>
              <div className="cosmos-account-activity__table-wrap"><table>
                <thead><tr><th>Activity</th><th>Amount / Detail</th><th>Height / Time</th><th>TX</th></tr></thead>
                <tbody>{state.items.map((item) => <tr key={item.tx_hash}>
                  <td><strong className={`cosmos-account-activity__action is-${actionTone(item)}`}>{item.success ? (ACTION_LABELS[item.action] || 'Transaction') : `Failed · ${ACTION_LABELS[item.action] || 'Transaction'}`}</strong>{item.type_url && <code className="cosmos-account-activity__type">{item.type_url}</code>}</td>
                  <td><AmountDetail item={item} network={network} market={market} /></td>
                  <td><a className="accent-value cosmos-account-activity__height" href={`/networks/${network.id}/blocks/${item.height}`}>#{item.height.toLocaleString()}</a><small>{utc(item.timestamp)}</small></td>
                  <td><a className="cosmos-account-activity__tx" href={`/networks/${network.id}/transactions/${item.tx_hash}`} title={item.tx_hash}>{shorten(item.tx_hash, 10, 6)}</a></td>
                </tr>)}</tbody>
              </table></div>
              {state.status === 'partial' && <p className="muted cosmos-account-activity__note">Some transaction-index sources are temporarily unavailable.</p>}
              {state.hasMore && state.page < 5 && <div className="cosmos-account-activity__more"><button type="button" disabled={state.loadingMore} onClick={showMore}>{state.loadingMore ? 'Loading…' : 'Show 10 more ↓'}</button></div>}
            </>}
  </section>
}
