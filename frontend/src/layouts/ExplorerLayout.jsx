import { useEffect, useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { TopBar } from '../components/TopBar'
import { useChainIdentity } from '../hooks/useChainIdentity'

export function ExplorerLayout({ children, healthState, nextFastRefreshAt, showRefreshCountdown = true, averageBlockTimeSeconds, averageBlockTimeSampleSize }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('utsa-gno-explorer.sidebar-collapsed') === 'true'
    } catch {
      return false
    }
  })
  const chainId = useChainIdentity()

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
        <TopBar onMenuClick={() => setSidebarOpen(true)} healthState={healthState} nextFastRefreshAt={nextFastRefreshAt} showRefreshCountdown={showRefreshCountdown} averageBlockTimeSeconds={averageBlockTimeSeconds} averageBlockTimeSampleSize={averageBlockTimeSampleSize} />
        <main className="main-content">{children}</main>
      </div>
    </div>
  )
}
