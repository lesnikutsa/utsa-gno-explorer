import { useEffect, useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { TopBar } from '../components/TopBar'
import { useChainIdentity } from '../hooks/useChainIdentity'
import { useTheme } from '../hooks/useTheme'

export function ExplorerLayout({ children, healthState, nextFastRefreshAt, showRefreshCountdown = true, averageBlockTimeSeconds, averageBlockTimeSampleSize, averageBlockTimeIntervalsSeconds, chainId: chainIdOverride, documentTitle }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('utsa-gno-explorer.sidebar-collapsed') === 'true'
    } catch {
      return false
    }
  })
  const chainId = useChainIdentity()
  const resolvedChainId = chainIdOverride ?? chainId
  // The Gno path remains equivalent to chainId={chainId}; Cosmos supplies its validated registry identity.
  const { theme, toggleTheme } = useTheme()

  useEffect(() => {
    if (documentTitle) document.title = documentTitle
  }, [documentTitle])

  useEffect(() => {
    try {
      window.localStorage.setItem('utsa-gno-explorer.sidebar-collapsed', String(sidebarCollapsed))
    } catch {
      // Storage can be unavailable in privacy-restricted browsing contexts.
    }
  }, [sidebarCollapsed])

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}>
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        chainId={resolvedChainId}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((collapsed) => !collapsed)}
      />
      <div className="app-frame">
        <TopBar onMenuClick={() => setSidebarOpen(true)} healthState={healthState} nextFastRefreshAt={nextFastRefreshAt} showRefreshCountdown={showRefreshCountdown} averageBlockTimeSeconds={averageBlockTimeSeconds} averageBlockTimeSampleSize={averageBlockTimeSampleSize} averageBlockTimeIntervalsSeconds={averageBlockTimeIntervalsSeconds} theme={theme} onToggleTheme={toggleTheme} />
        <main className="main-content">{typeof children === 'function' ? children(chainId) : children}</main>
      </div>
    </div>
  )
}
