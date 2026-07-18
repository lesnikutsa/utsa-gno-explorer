import { DataTable } from '../components/DataTable'
import { useBlocksPage } from '../hooks/useBlocksPage'
import { shortAddress } from '../utils/address'
import { relativeTime } from '../utils/time'

const columns = [
  {
    key: 'height',
    label: 'Height',
    render: (block) => <a className="blocks-table__height mono" href={`/blocks/${block.height}`}>#{block.height.toLocaleString()}</a>,
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

export function Blocks() {
  const { blocks, loading, error, refresh } = useBlocksPage()

  return (
    <section className="blocks-page" aria-labelledby="blocks-page-title">
      <header className="blocks-page__header">
        <div>
          <h1 id="blocks-page-title">Blocks</h1>
          <p>Latest finalized blocks indexed by UTSA Explorer.</p>
        </div>
        <button className="blocks-page__refresh" type="button" onClick={refresh} disabled={loading}>Refresh</button>
      </header>

      {error && <div className="blocks-page__error" role="alert">Blocks could not be loaded. Please try again.</div>}

      <div className="panel blocks-page__table">
        <DataTable
          columns={columns}
          rows={blocks}
          rowKey={(block) => block.height}
          loading={loading}
          emptyMessage={error ? 'Blocks are currently unavailable.' : 'No blocks have been indexed yet.'}
        />
      </div>
    </section>
  )
}
