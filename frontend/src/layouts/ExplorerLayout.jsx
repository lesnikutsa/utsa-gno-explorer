import { useEffect, useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { TopBar } from '../components/TopBar'
import { useChainIdentity } from '../hooks/useChainIdentity'
import { useTheme } from '../hooks/useTheme'

export function ExplorerLayout({ children, healthState, nextFastRefreshAt, showRefreshCountdown = true, averageBlockTimeSeconds, averageBlockTimeSampleSize, averageBlockTimeIntervalsSeconds, chainId: chainIdOverride, searchEnabled = true, documentTitle }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('utsa-gno-explorer.sidebar-collapsed') === 'true'
    } catch {
      return false
    }
  })
  const liveChainId = useChainIdentity({ enabled: chainIdOverride === undefined })
  const chainId = chainIdOverride ?? liveChainId
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
        chainId={chainId}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((collapsed) => !collapsed)}
      />
      <div className="app-frame">
        <TopBar onMenuClick={() => setSidebarOpen(true)} healthState={healthState} nextFastRefreshAt={nextFastRefreshAt} showRefreshCountdown={showRefreshCountdown} averageBlockTimeSeconds={averageBlockTimeSeconds} averageBlockTimeSampleSize={averageBlockTimeSampleSize} averageBlockTimeIntervalsSeconds={averageBlockTimeIntervalsSeconds} theme={theme} onToggleTheme={toggleTheme} searchEnabled={searchEnabled} />
        <main className="main-content">{typeof children === 'function' ? children(chainId) : children}</main>
      </div>
    </div>
  )
}
