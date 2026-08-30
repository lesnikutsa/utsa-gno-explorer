import { useEffect } from 'react'
import { useSelectedNetwork } from '../context/SelectedNetworkContext'
import { navigateInternal } from '../utils/navigation'
import { useTheme } from '../hooks/useTheme'

export function CosmosLayout({ network, section, children }) {
  const { selectNetwork } = useSelectedNetwork()
  const { theme, toggleTheme } = useTheme()
  useEffect(() => { selectNetwork(network.id); document.title = `${network.presentation.projectName} Explorer` }, [network.id, selectNetwork])
  return <div className="cosmos-shell">
    <aside className="cosmos-sidebar">
      <strong>UTSA Explorer</strong><small>AtomOne · Mainnet</small>
      <nav><a className={section === 'overview' ? 'is-active' : ''} href={`/networks/${network.id}`}>Overview</a>
        <a className={section === 'blocks' ? 'is-active' : ''} href={`/networks/${network.id}/blocks`}>Blocks</a></nav>
      <button onClick={() => navigateInternal('/')}>Switch to Gno.land</button>
    </aside>
    <div className="cosmos-main"><header><span>AtomOne <code>atomone-1</code></span><button onClick={toggleTheme}>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</button></header><main>{children}</main></div>
  </div>
}
