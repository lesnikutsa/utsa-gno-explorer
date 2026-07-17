export function TopBar({ onMenuClick, health }) {
  return (
    <header className="topbar">
      <button className="menu-button" onClick={onMenuClick} aria-label="Open navigation">☰</button>
      <label className="search-box">
        <span aria-hidden="true">⌕</span>
        <input type="search" placeholder="Search by height, tx hash, address, validator..." aria-label="Search explorer" />
        <kbd>/</kbd>
      </label>
      <div className="network-update">
        <span className={`pulse ${health === false ? 'pulse--error' : ''}`} />
        <div><span>Network update</span><strong>{health === false ? 'Connection error' : 'Live data'}</strong></div>
      </div>
    </header>
  )
}
