import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Blocks } from './pages/Blocks'
import { BlockDetail } from './pages/BlockDetail'
import { Overview } from './pages/Overview'
import { ValidatorDetail } from './pages/ValidatorDetail'
import { Validators } from './pages/Validators'
import { useBlocksPage } from './hooks/useBlocksPage'
import { useBlockDetail } from './hooks/useBlockDetail'
import { useExplorerData } from './hooks/useExplorerData'
import { useValidatorDetail } from './hooks/useValidatorDetail'
import { useValidatorsPage } from './hooks/useValidatorsPage'

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

function BlockDetailPage({ height }) {
  const blockDetail = useBlockDetail(height)

  return (
    <ExplorerLayout healthState={blockDetail.healthState} showRefreshCountdown={false}>
      <BlockDetail blockDetail={blockDetail} />
    </ExplorerLayout>
  )
}

function ValidatorsPage() {
  const validatorsPage = useValidatorsPage()

  return (
    <ExplorerLayout healthState={validatorsPage.healthState} showRefreshCountdown={false}>
      <Validators validatorsPage={validatorsPage} />
    </ExplorerLayout>
  )
}

function ValidatorDetailPage({ address }) {
  const validatorDetail = useValidatorDetail(address)

  return (
    <ExplorerLayout healthState={validatorDetail.healthState} showRefreshCountdown={false}>
      <ValidatorDetail validatorDetail={validatorDetail} />
    </ExplorerLayout>
  )
}

export default function App() {
  const path = window.location.pathname

  if (path === '/blocks' || path === '/blocks/') {
    return <BlocksPage />
  }

  if (path === '/validators' || path === '/validators/') {
    return <ValidatorsPage />
  }

  const validatorDetailMatch = path.match(/^\/validators\/([^/]+)\/?$/)
  if (validatorDetailMatch) {
    return <ValidatorDetailPage address={validatorDetailMatch[1]} />
  }

  if (path.startsWith('/blocks/')) {
    const height = path.slice('/blocks/'.length).replace(/\/$/, '')
    return <BlockDetailPage height={height} />
  }

  return <OverviewPage />
}
