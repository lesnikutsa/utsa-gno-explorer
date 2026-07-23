import { ExplorerLayout } from './layouts/ExplorerLayout'
import { Blocks } from './pages/Blocks'
import { BlockDetail } from './pages/BlockDetail'
import { TransactionDetail } from './pages/TransactionDetail'
import { Overview } from './pages/Overview'
import { ValidatorDetail } from './pages/ValidatorDetail'
import { Validators } from './pages/Validators'
import { Network } from './pages/Network'
import { useBlocksPage } from './hooks/useBlocksPage'
import { useBlockDetail } from './hooks/useBlockDetail'
import { useTransactionDetail } from './hooks/useTransactionDetail'
import { useExplorerData } from './hooks/useExplorerData'
import { useValidatorDetail } from './hooks/useValidatorDetail'
import { useValidatorsPage } from './hooks/useValidatorsPage'
import { useNetworkPage } from './hooks/useNetworkPage'

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

function TransactionDetailPage({ height, index }) {
  const transactionDetail = useTransactionDetail(height, index)

  return (
    <ExplorerLayout healthState={transactionDetail.healthState} showRefreshCountdown={false}>
      <TransactionDetail transactionDetail={transactionDetail} routeHeight={height} />
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

function NetworkPage() {
  const networkPage = useNetworkPage()
  return (
    <ExplorerLayout healthState={networkPage.healthState} nextFastRefreshAt={networkPage.nextRefreshAt}>
      <Network networkPage={networkPage} />
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

  if (path === '/network' || path === '/network/') {
    return <NetworkPage />
  }

  const validatorDetailMatch = path.match(/^\/validators\/([^/]+)\/?$/)
  if (validatorDetailMatch) {
    return <ValidatorDetailPage address={validatorDetailMatch[1]} />
  }

  const transactionDetailMatch = path.match(/^\/blocks\/([^/]+)\/transactions\/([^/]+)\/?$/)
  if (transactionDetailMatch) {
    return <TransactionDetailPage height={transactionDetailMatch[1]} index={transactionDetailMatch[2]} />
  }

  if (path.startsWith('/blocks/')) {
    const height = path.slice('/blocks/'.length).replace(/\/$/, '')
    return <BlockDetailPage height={height} />
  }

  return <OverviewPage />
}
