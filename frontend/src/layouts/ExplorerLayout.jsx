import { useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { TopBar } from '../components/TopBar'
import { useChainIdentity } from '../hooks/useChainIdentity'

export function ExplorerLayout({ children, healthState, nextFastRefreshAt, showRefreshCountdown = true }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const chainId = useChainIdentity()

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} chainId={chainId} />
      <div className="app-frame">
        <TopBar onMenuClick={() => setSidebarOpen(true)} healthState={healthState} nextFastRefreshAt={nextFastRefreshAt} showRefreshCountdown={showRefreshCountdown} />
        <main className="main-content">{children}</main>
      </div>
    </div>
  )
}
