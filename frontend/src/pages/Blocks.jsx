import { useEffect, useRef, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { ProposerIdentity } from '../components/ProposerIdentity'
import { shortAddress } from '../utils/address'
import { relativeTime } from '../utils/time'

const columns = [
  {
    key: 'height',
    label: 'Height',
    render: (block) => <a className="table-link" href={`/blocks/${block.height}`}><span className="blocks-table__height accent-value mono">#{block.height.toLocaleString()}</span></a>,
  },
  { key: 'time', label: 'Time', render: (block) => relativeTime(block.time) },
  {
    key: 'proposer_address',
    label: 'Proposer',
    render: (block) => <ProposerIdentity address={block.proposer_address} moniker={block.proposer_moniker} compact />,
  },
  { key: 'tx_count', label: 'Txs' },
  {
    key: 'block_hash',
    label: 'Block Hash',
    render: (block) => <span className="mono muted" title={block.block_hash}>{shortAddress(block.block_hash)}</span>,
  },
]

export function Blocks({ blocksPage }) {
  const previousFirstBlockHeight = useRef(null)
  const [insertedBlockHeight, setInsertedBlockHeight] = useState(null)
  const {
    blocks,
    loading,
    manualRefreshing,
    error,
    nextBeforeHeight,
    pageIndex,
    loadOlder,
    loadNewer,
    refresh,
  } = blocksPage

  const emptyMessage = error ? 'Blocks are currently unavailable.' : 'No blocks have been indexed yet.'

  const firstBlockHeight = blocks[0]?.height ?? null
  const latestMode = pageIndex === 0

  useEffect(() => {
    if (!latestMode || loading) {
      previousFirstBlockHeight.current = null
      setInsertedBlockHeight(null)
      return undefined
    }

    if (error || firstBlockHeight === null) return undefined

    let animationTimer
    if (previousFirstBlockHeight.current !== null && firstBlockHeight !== previousFirstBlockHeight.current) {
      setInsertedBlockHeight(firstBlockHeight)
      animationTimer = window.setTimeout(() => setInsertedBlockHeight(null), 900)
    }
    previousFirstBlockHeight.current = firstBlockHeight

    return () => {
      if (animationTimer !== undefined) window.clearTimeout(animationTimer)
    }
  }, [error, firstBlockHeight, latestMode, loading])

  return (
    <section className="blocks-page" aria-labelledby="blocks-page-title">
      <header className="blocks-page__header">
        <div>
          <h1 id="blocks-page-title">Blocks</h1>
          <p>Latest finalized blocks indexed by UTSA Explorer.</p>
        </div>
        {pageIndex === 0 && (
          <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={refresh} disabled={loading || manualRefreshing}>
            {manualRefreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        )}
      </header>

      <div className="panel blocks-page__table">
        <DataTable
          columns={columns}
          rows={blocks}
          rowKey={(block) => block.height}
          rowClassName={(block, index) => insertedBlockHeight === null ? '' : index === 0 && block.height === insertedBlockHeight ? 'is-new-row' : 'is-settling-row'}
          loading={loading}
          emptyMessage={emptyMessage}
        />
      </div>

      <nav className="blocks-pagination" aria-label="Blocks pagination">
        <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || manualRefreshing || pageIndex === 0}>Newer blocks</button>
        <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
        <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || manualRefreshing || nextBeforeHeight === null}>Older blocks</button>
      </nav>
    </section>
  )
}
