export function DataTable({ columns, rows, rowKey, rowClassName, emptyMessage, loading, sortKey, sortDirection, onSort }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr>{columns.map((column) => {
          const active = column.sortable && sortKey === column.key
          const ariaSort = column.sortable ? (active ? sortDirection : 'none') : undefined
          const nextDirection = active
            ? (sortDirection === 'ascending' ? 'descending' : 'ascending')
            : (column.defaultSortDirection ?? 'ascending')
          const sortLabel = `${column.label}: ${active ? `sorted ${sortDirection}` : 'not sorted'}. Activate to sort ${nextDirection}.`

          return (
            <th key={column.key} aria-sort={ariaSort}>
              {column.sortable && onSort ? (
                <button className={`data-table__sort ${active ? 'is-active' : ''}`} type="button" onClick={() => onSort(column.key, nextDirection)} aria-label={sortLabel} title={column.headerTitle}>
                  <span>{column.label}</span>
                  <span className="data-table__sort-arrow" aria-hidden="true">{active ? (sortDirection === 'ascending' ? '↑' : '↓') : '↕'}</span>
                </button>
              ) : column.label}
            </th>
          )
        })}</tr></thead>
        <tbody>
          {loading && <tr><td className="table-message" colSpan={columns.length}>Loading live data…</td></tr>}
          {!loading && rows.length === 0 && <tr><td className="table-message" colSpan={columns.length}>{emptyMessage}</td></tr>}
          {!loading && rows.map((row, index) => (
            <tr key={rowKey(row)} className={rowClassName?.(row, index) ?? ''}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
