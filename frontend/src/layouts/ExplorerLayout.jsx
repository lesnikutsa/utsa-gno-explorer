import { useState } from 'react'
import { Sidebar } from '../components/Sidebar'
import { TopBar } from '../components/TopBar'

export function ExplorerLayout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="app-frame">
        <TopBar onMenuClick={() => setSidebarOpen(true)} />
        <main className="main-content">{children}</main>
      </div>
    </div>
  )
}
