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
  const {
    blocks,
    loading,
    backgroundRefreshing,
    manualRefreshing,
    error,
    nextBeforeHeight,
    pageIndex,
    searchInput,
    setSearchInput,
    searchQuery,
    searchMode,
    searchNotFound,
    loadOlder,
    loadNewer,
    refresh,
    submitSearch,
    resetSearch,
  } = blocksPage

  const emptyMessage = searchNotFound
    ? 'Block not found.'
    : error
      ? 'Blocks are currently unavailable.'
      : searchMode
        ? 'Block not found.'
        : 'No blocks have been indexed yet.'

  return (
    <section className="blocks-page" aria-labelledby="blocks-page-title">
      <header className="blocks-page__header">
        <div>
          <h1 id="blocks-page-title">Blocks</h1>
          <p>Latest finalized blocks indexed by UTSA Explorer.</p>
        </div>
        {!searchMode && pageIndex === 0 && (
          <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={refresh} disabled={loading || manualRefreshing}>
            {manualRefreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        )}
      </header>

      <form className="blocks-search" role="search" onSubmit={submitSearch}>
        <input
          type="search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Search by exact height or block hash"
          aria-label="Search blocks by exact height or block hash"
          disabled={loading}
        />
        <button className="blocks-page__button blocks-page__button--accent" type="submit" disabled={loading || backgroundRefreshing || manualRefreshing || !searchInput.trim()}>Search</button>
        {searchMode && <button className="blocks-page__button" type="button" onClick={resetSearch} disabled={loading}>Reset</button>}
      </form>

      {searchMode && <p className="blocks-page__context">Showing exact search result for <span className="mono">{searchQuery}</span></p>}

      <div className="panel blocks-page__table">
        <DataTable
          columns={columns}
          rows={blocks}
          rowKey={(block) => block.height}
          loading={loading}
          emptyMessage={emptyMessage}
        />
      </div>

      {!searchMode && (
        <nav className="blocks-pagination" aria-label="Blocks pagination">
          <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || manualRefreshing || pageIndex === 0}>Newer blocks</button>
          <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
          <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || manualRefreshing || nextBeforeHeight === null}>Older blocks</button>
        </nav>
      )}
    </section>
  )
}
