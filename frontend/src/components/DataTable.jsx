export function DataTable({ columns, rows, rowKey, emptyMessage, loading }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {loading && <tr><td className="table-message" colSpan={columns.length}>Loading live data…</td></tr>}
          {!loading && rows.length === 0 && <tr><td className="table-message" colSpan={columns.length}>{emptyMessage}</td></tr>}
          {!loading && rows.map((row) => (
            <tr key={rowKey(row)}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
