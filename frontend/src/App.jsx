import { useEffect } from 'react'
import { ExplorerLayout } from './layouts/ExplorerLayout'
import { networkProfile } from './config/networkProfile'
import { Blocks } from './pages/Blocks'
import { BlockDetail } from './pages/BlockDetail'
import { TransactionDetail } from './pages/TransactionDetail'
import { Transactions } from './pages/Transactions'
import { Realms } from './pages/Realms'
import { RealmDetail } from './pages/RealmDetail'
import { Overview } from './pages/Overview'
import { ValidatorDetail } from './pages/ValidatorDetail'
import { Validators } from './pages/Validators'
import { Governance } from './pages/Governance'
import { GovernanceDetail } from './pages/GovernanceDetail'
import { AccountDetail } from './pages/AccountDetail'
import { useBlocksPage } from './hooks/useBlocksPage'
import { useBlockDetail } from './hooks/useBlockDetail'
import { useTransactionDetail } from './hooks/useTransactionDetail'
import { useTransactionsPage } from './hooks/useTransactionsPage'
import { useRealmsPage } from './hooks/useRealmsPage'
import { useRealmApplications } from './hooks/useRealmApplications'
import { useRealmsAutoRefresh } from './hooks/useRealmsAutoRefresh'
import { useExplorerData } from './hooks/useExplorerData'
import { useValidatorDetail } from './hooks/useValidatorDetail'
import { useValidatorsPage } from './hooks/useValidatorsPage'
import { useGovernancePage } from './hooks/useGovernancePage'
import { useGovernanceDetail } from './hooks/useGovernanceDetail'
import { useAccountDetail } from './hooks/useAccountDetail'

const NETWORK_MASCOT_SRC = '/assets/network-mascot.png?v=1'

function OverviewPage() {
  const explorerData = useExplorerData()

  return (
    <ExplorerLayout
      healthState={explorerData.healthState}
      nextFastRefreshAt={explorerData.nextFastRefreshAt}
      averageBlockTimeSeconds={explorerData.data.network?.average_block_time_seconds}
      averageBlockTimeSampleSize={explorerData.data.network?.average_block_time_sample_size}
    >
      <Overview
        explorerData={explorerData}
        mascotSrc={NETWORK_MASCOT_SRC}
      />
    </ExplorerLayout>
  )
}

function BlocksPage() {
  const blocksPage = useBlocksPage()
  const showRefreshCountdown = blocksPage.pageIndex === 0 && Boolean(blocksPage.nextRefreshAt)

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

function TransactionsPage() {
  const transactionsPage = useTransactionsPage()

  return (
    <ExplorerLayout healthState={transactionsPage.healthState} showRefreshCountdown={false}>
      <Transactions transactionsPage={transactionsPage} />
    </ExplorerLayout>
  )
}

function RealmsPage() {
  const realmsPage = useRealmsPage()
  const realmApplications = useRealmApplications()
  useRealmsAutoRefresh({
    enabled: realmsPage.pageIndex === 0 && !realmsPage.loading && !realmApplications.loading,
    refreshRealms: realmsPage.refreshInBackground,
    refreshApplications: realmApplications.refreshInBackground,
  })

  return (
    <ExplorerLayout healthState={realmsPage.healthState} showRefreshCountdown={false}>
      <Realms realmsPage={realmsPage} realmApplications={realmApplications} />
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
function AccountDetailPage({ address }) {
  const accountDetail = useAccountDetail(address)

  return (
    <ExplorerLayout healthState={accountDetail.healthState} showRefreshCountdown={false}>
      <AccountDetail accountDetail={accountDetail} />
    </ExplorerLayout>
  )
}
function GovernancePage() {
  const governancePage = useGovernancePage()

  return (
    <ExplorerLayout healthState={governancePage.healthState} showRefreshCountdown={false}>
      <Governance governancePage={governancePage} />
    </ExplorerLayout>
  )
}

function GovernanceDetailPage({ proposalId }) {
  const governanceDetail = useGovernanceDetail(proposalId)

  return (
    <ExplorerLayout healthState={governanceDetail.healthState} showRefreshCountdown={false}>
      <GovernanceDetail governanceDetail={governanceDetail} />
    </ExplorerLayout>
  )
}

export default function App() {
  const path = window.location.pathname

  useEffect(() => {
    document.title = `${networkProfile.projectName} Explorer`
    const descriptionMeta = document.querySelector('meta[name="description"]')
    if (descriptionMeta) descriptionMeta.setAttribute('content', networkProfile.description)
  }, [])

  if (path === '/blocks' || path === '/blocks/') {
    return <BlocksPage />
  }

  if (path === '/validators' || path === '/validators/') {
    return <ValidatorsPage />
  }

  if (path === '/transactions' || path === '/transactions/') {
    return <TransactionsPage />
  }
  if (path === '/realms' || path === '/realms/') {
    return <RealmsPage />
  }
  if (path === '/realm' || path === '/realm/') {
    return <ExplorerLayout healthState="loading" showRefreshCountdown={false}><RealmDetail /></ExplorerLayout>
  }
  if (path === '/governance' || path === '/governance/') {
    return <GovernancePage />
  }

  const governanceDetailMatch = path.match(/^\/governance\/([^/]+)\/?$/)
  if (governanceDetailMatch) {
    return <GovernanceDetailPage proposalId={governanceDetailMatch[1]} />
  }

  const validatorDetailMatch = path.match(/^\/validators\/([^/]+)\/?$/)
  if (validatorDetailMatch) {
    return <ValidatorDetailPage address={validatorDetailMatch[1]} />
  }

  const accountDetailMatch = path.match(/^\/accounts\/([^/]+)\/?$/)
  if (accountDetailMatch) {
    return <AccountDetailPage address={accountDetailMatch[1]} />
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
