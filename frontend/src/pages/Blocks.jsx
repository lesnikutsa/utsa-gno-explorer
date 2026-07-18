import { DataTable } from '../components/DataTable'
import { shortAddress } from '../utils/address'
import { relativeTime } from '../utils/time'

const columns = [
  {
    key: 'height',
    label: 'Height',
    render: (block) => <span className="blocks-table__height mono">#{block.height.toLocaleString()}</span>,
  },
  { key: 'time', label: 'Time', render: (block) => relativeTime(block.time) },
  {
    key: 'proposer_address',
    label: 'Proposer',
    render: (block) => <span className="mono muted" title={block.proposer_address}>{shortAddress(block.proposer_address)}</span>,
  },
  { key: 'tx_count', label: 'Txs' },
  {
    key: 'block_hash',
    label: 'Block Hash',
    render: (block) => <span className="mono muted" title={block.block_hash}>{shortAddress(block.block_hash)}</span>,
  },
]

export function Blocks({ blocksPage }) {
  const { blocks, loading, error, refresh } = blocksPage

  return (
    <section className="blocks-page" aria-labelledby="blocks-page-title">
      <header className="blocks-page__header">
        <div>
          <h1 id="blocks-page-title">Blocks</h1>
          <p>Latest finalized blocks indexed by UTSA Explorer.</p>
        </div>
        <button className="blocks-page__refresh" type="button" onClick={refresh} disabled={loading}>Refresh</button>
      </header>

      <div className="panel blocks-page__table">
        <DataTable
          columns={columns}
          rows={error ? [] : blocks}
          rowKey={(block) => block.height}
          loading={loading}
          emptyMessage={error ? 'Blocks are currently unavailable.' : 'No blocks have been indexed yet.'}
        />
      </div>
    </section>
  )
}
