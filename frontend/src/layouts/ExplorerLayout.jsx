import { useEffect, useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { TopBar } from '../components/TopBar'
import { useChainIdentity } from '../hooks/useChainIdentity'
import { useTheme } from '../hooks/useTheme'
import { useSelectedNetwork } from '../context/SelectedNetworkContext'

function GnoChainIdentity({ children }) {
  const chainId = useChainIdentity()
  return children(chainId)
}

export function ExplorerLayout({ children, healthState, chainId: providedChainId, nextFastRefreshAt, showRefreshCountdown = true, averageBlockTimeSeconds, averageBlockTimeSampleSize, averageBlockTimeIntervalsSeconds }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('utsa-gno-explorer.sidebar-collapsed') === 'true'
    } catch {
      return false
    }
  })
  const { selectedNetwork } = useSelectedNetwork()
  const { theme, toggleTheme } = useTheme()

  useEffect(() => {
    try {
      window.localStorage.setItem('utsa-gno-explorer.sidebar-collapsed', String(sidebarCollapsed))
    } catch {
      // Storage can be unavailable in privacy-restricted browsing contexts.
    }
  }, [sidebarCollapsed])

  const renderLayout = (chainId) => (
    <div className={`app-shell ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}>
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        chainId={chainId}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((collapsed) => !collapsed)}
      />
      <div className="app-frame">
        <TopBar network={selectedNetwork} onMenuClick={() => setSidebarOpen(true)} healthState={healthState} nextFastRefreshAt={nextFastRefreshAt} showRefreshCountdown={showRefreshCountdown} averageBlockTimeSeconds={averageBlockTimeSeconds} averageBlockTimeSampleSize={averageBlockTimeSampleSize} averageBlockTimeIntervalsSeconds={averageBlockTimeIntervalsSeconds} theme={theme} onToggleTheme={toggleTheme} />
        <main className="main-content">{typeof children === 'function' ? children(chainId) : children}</main>
      </div>
    </div>
  )
  return selectedNetwork.family === 'cosmos'
    ? renderLayout(providedChainId || selectedNetwork.expectedChainId)
    : <GnoChainIdentity>{renderLayout}</GnoChainIdentity>
}
