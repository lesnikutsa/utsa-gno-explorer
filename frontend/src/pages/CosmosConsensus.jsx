import { useMemo } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import '../styles/cosmos-consensus.css'

const shortHash = (value) => value && value !== 'NIL'
  ? `${value.slice(0, 8)}…${value.slice(-6)}` : (value || '—')

const formatPercent = (value) => `${Number(value || 0).toFixed(value >= 99.995 ? 2 : 1)}%`

const leadingHash = (groups = []) => groups.find((item) => item.hash !== 'NIL')?.hash || null

function Metric({ label, value, meta }) {
  return <article className="card status-card cosmos-validator-summary__card cosmos-consensus__metric">
    <span>{label}</span><strong>{value}</strong>{meta && <small>{meta}</small>}
  </article>
}

function HashGroups({ groups, missing }) {
  if (!groups?.length && Number(missing) >= 99.99) return <span className="cosmos-consensus__hash-empty">Waiting for votes…</span>
  return <div className="cosmos-consensus__hash-groups">
    {groups?.slice(0, 4).map((item) => <span key={item.hash} className={item.hash === 'NIL' ? 'is-nil' : ''}>
      <b>{shortHash(item.hash)}</b> {formatPercent(item.percent)}
    </span>)}
    {Number(missing) > 0.01 && <span className="is-missing"><b>Missing</b> {formatPercent(missing)}</span>}
  </div>
}

function VoteBar({ label, power, quorum, groups, missing }) {
  return <div className="cosmos-consensus__vote-row">
    <div className="cosmos-consensus__vote-heading">
      <div><span>{label}</span><strong>{formatPercent(power)}</strong></div>
      <small>{quorum ? '2/3 reached' : 'Waiting for 2/3'}</small>
    </div>
    <div className="cosmos-consensus__progress" aria-label={`${label} ${formatPercent(power)}`}>
      <span className={quorum ? 'is-quorum' : ''} style={{ width: `${Math.max(0, Math.min(100, Number(power) || 0))}%` }} />
      <i aria-hidden="true" />
    </div>
    <HashGroups groups={groups} missing={missing} />
  </div>
}

function voteClass(state, hash, leader) {
  if (state === 'signed') return leader && hash && hash !== leader ? 'is-divergent' : 'is-signed'
  if (state === 'nil') return 'is-nil'
  if (state === 'missing') return 'is-missing'
  return 'is-unknown'
}

function VoteIndicator({ label, state, hash, leader }) {
  const text = state === 'signed' ? (leader && hash !== leader ? 'other hash' : 'signed')
    : state === 'nil' ? 'nil vote' : state === 'missing' ? 'not seen yet' : 'unknown'
  return <span className={`cosmos-consensus__vote-indicator ${voteClass(state, hash, leader)}`} aria-label={`${label}: ${text}`}>
    <b>{label}</b><i />
  </span>
}

function ValidatorGrid({ network, validators, prevoteLeader, precommitLeader }) {
  const sorted = useMemo(() => [...(validators || [])].sort((a, b) => b.voting_power - a.voting_power), [validators])
  return <div className="cosmos-consensus__validator-grid">
    {sorted.map((validator, index) => {
      const content = <>
        <span className="cosmos-consensus__validator-rank">{index + 1}</span>
        <span className="cosmos-consensus__validator-name">{validator.proposer && <em>★</em>}{validator.moniker}</span>
        <span className="cosmos-consensus__validator-power">{formatPercent(validator.voting_power_percent)}</span>
        <span className="cosmos-consensus__validator-votes">
          <VoteIndicator label="PV" state={validator.prevote} hash={validator.prevote_hash} leader={prevoteLeader} />
          <VoteIndicator label="PC" state={validator.precommit} hash={validator.precommit_hash} leader={precommitLeader} />
        </span>
      </>
      return validator.operator_address
        ? <a className="cosmos-consensus__validator" href={`/networks/${network.id}/validators/${validator.operator_address}`} key={validator.consensus_address}>{content}</a>
        : <div className="cosmos-consensus__validator" key={validator.consensus_address}>{content}</div>
    })}
  </div>
}

function RpcViews({ data }) {
  if (!data.rpc_views?.length) return null
  return <details className="panel cosmos-consensus__rpc" defaultOpen={data.rpc_diverged || data.rpc_height_spread > 2}>
    <summary><span>RPC views</span><small>{data.rpc_diverged ? 'Different finalized hashes detected' : `Height spread ${data.rpc_height_spread}`}</small></summary>
    <div className="cosmos-consensus__rpc-grid">
      {data.rpc_views.map((item) => <div className={`cosmos-consensus__rpc-item is-${item.status}`} key={item.provider}>
        <strong>{item.provider}</strong><span>{item.status.replace('_', ' ')}</span>
        <b>{item.height == null ? '—' : `#${Number(item.height).toLocaleString('en-US')}`}</b>
        <code>{shortHash(item.block_hash)}</code>
      </div>)}
    </div>
  </details>
}

export function CosmosConsensus({ network }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/consensus`, 1000)
  if (resource.loading && !resource.data) return <section className="cosmos-consensus"><header className="cosmos-validators__heading"><h1>Consensus</h1></header><div className="panel"><p className="muted">Loading live consensus…</p></div></section>
  if (!resource.data) return <section className="cosmos-consensus"><header className="cosmos-validators__heading"><h1>Consensus</h1></header><div className="panel"><p className="cosmos-error">Consensus data is temporarily unavailable.</p></div></section>

  const data = resource.data
  const prevoteLeader = leadingHash(data.prevote_hashes)
  const precommitLeader = leadingHash(data.precommit_hashes)
  const warnings = []
  if (data.rpc_diverged) warnings.push('RPC providers disagree on a finalized block hash.')
  if (data.competing_precommit_hashes) warnings.push('Multiple precommit block hashes are visible in the current round.')
  else if (data.competing_prevote_hashes) warnings.push('Multiple prevote block hashes are visible in the current round.')
  if (data.rpc_height_spread > 2) warnings.push(`RPC height spread is ${data.rpc_height_spread} blocks.`)

  const updated = new Date(data.updated_at)
  const updatedLabel = Number.isNaN(updated.getTime()) ? 'now' : `${updated.toISOString().slice(11, 19)} UTC`

  return <section className="cosmos-consensus">
    <header className="cosmos-consensus__title cosmos-validators__heading">
      <h1>Consensus</h1><span><i /> Live · every 1s</span>
    </header>

    <div className="cosmos-validator-summary cosmos-consensus__summary">
      <Metric label="Height" value={`#${Number(data.height).toLocaleString('en-US')}`} meta={data.proposer_moniker ? `Proposer: ${data.proposer_moniker}` : null} />
      <Metric label="Round" value={data.round} meta={`Updated ${updatedLabel}`} />
      <Metric label="Step" value={data.step_label} meta={`Step ${data.step}`} />
      <Metric label="Precommit power" value={formatPercent(data.precommit_power_percent)} meta={data.precommit_quorum ? '2/3 reached' : 'Consensus in progress'} />
    </div>

    {warnings.length > 0 && <div className="cosmos-consensus__alerts">{warnings.map((warning) => <div key={warning}><b>Consensus warning</b><span>{warning}</span></div>)}</div>}

    <section className="panel cosmos-consensus__live">
      <div className="panel__heading"><h2>Live Consensus</h2><span>Height #{Number(data.height).toLocaleString('en-US')} · Round {data.round}</span></div>
      <div className="cosmos-consensus__live-body">
        <VoteBar label="Prevote" power={data.prevote_power_percent} quorum={data.prevote_quorum} groups={data.prevote_hashes} missing={data.prevote_missing_percent} />
        <VoteBar label="Precommit" power={data.precommit_power_percent} quorum={data.precommit_quorum} groups={data.precommit_hashes} missing={data.precommit_missing_percent} />
        <div className="cosmos-consensus__hash-state">
          <span><small>Proposal hash</small><code>{shortHash(data.proposal_block_hash)}</code></span>
          <span><small>Locked hash</small><code>{shortHash(data.locked_block_hash)}</code></span>
          <span><small>Valid hash</small><code>{shortHash(data.valid_block_hash)}</code></span>
        </div>
      </div>
    </section>

    <section className="panel cosmos-consensus__validators">
      <div className="panel__heading cosmos-consensus__validators-heading">
        <h2>Validators <span>{data.validators.length}</span></h2>
        <div className="cosmos-consensus__legend"><span className="is-signed">Signed</span><span className="is-nil">Nil</span><span className="is-divergent">Other hash</span><span className="is-missing">Not seen yet</span></div>
      </div>
      <ValidatorGrid network={network} validators={data.validators} prevoteLeader={prevoteLeader} precommitLeader={precommitLeader} />
    </section>

    <RpcViews data={data} />
  </section>
}
