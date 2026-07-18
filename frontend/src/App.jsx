import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Blocks } from './pages/Blocks'
import { Overview } from './pages/Overview'
import { useBlocksPage } from './hooks/useBlocksPage'
import { useExplorerData } from './hooks/useExplorerData'

const NETWORK_MASCOT_SRC = '/assets/network-mascot.png?v=1'

function OverviewPage() {
  const explorerData = useExplorerData()

  return (
    <ExplorerLayout healthState={explorerData.healthState} nextFastRefreshAt={explorerData.nextFastRefreshAt}>
      <Overview
        explorerData={explorerData}
        mascotSrc={NETWORK_MASCOT_SRC}
      />
    </ExplorerLayout>
  )
}

function BlocksPage() {
  const blocksPage = useBlocksPage()
  const showRefreshCountdown = !blocksPage.searchMode && blocksPage.pageIndex === 0 && Boolean(blocksPage.nextRefreshAt)

  return (
    <ExplorerLayout
      healthState={blocksPage.healthState}
      nextFastRefreshAt={blocksPage.nextRefreshAt}
      showRefreshCountdown={showRefreshCountdown}
    >
      <Blocks blocksPage={blocksPage} />
    </ExplorerLayout>
  )
}

export default function App() {
  if (window.location.pathname === '/blocks') {
    return <BlocksPage />
  }

  return <OverviewPage />
}
