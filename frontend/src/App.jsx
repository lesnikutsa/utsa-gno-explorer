import { useEffect } from 'react'
import { ExplorerLayout } from './layouts/ExplorerLayout'
import { networkProfile } from './config/networkProfile'
import { Blocks } from './pages/Blocks'
import { BlockDetail } from './pages/BlockDetail'
import { TransactionDetail } from './pages/TransactionDetail'
import { Transactions } from './pages/Transactions'
import { Realms } from './pages/Realms'
import { Tokens } from './pages/Tokens'
import { RealmDetail } from './pages/RealmDetail'
import { decodeRealmDetailPath } from './utils/realm'
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
import { useTokensPage } from './hooks/useTokensPage'
import { useRealmApplications } from './hooks/useRealmApplications'
import { useTokensAutoRefresh } from './hooks/useTokensAutoRefresh'
import { useRealmsAutoRefresh } from './hooks/useRealmsAutoRefresh'
import { useExplorerData } from './hooks/useExplorerData'
import { useValidatorDetail } from './hooks/useValidatorDetail'
import { useValidatorsPage } from './hooks/useValidatorsPage'
import { useGovernancePage } from './hooks/useGovernancePage'
import { useGovernanceDetail } from './hooks/useGovernanceDetail'
import { useAccountDetail } from './hooks/useAccountDetail'
import { useRealmDetail } from './hooks/useRealmDetail'
import { usePathname } from './utils/navigation'
import { useSelectedNetwork } from './context/SelectedNetworkContext'
import { CosmosOverview } from './pages/CosmosOverview'
import { CosmosBlocks } from './pages/CosmosBlocks'
import { CosmosBlockDetail } from './pages/CosmosBlockDetail'
import { CosmosTransactions } from './pages/CosmosTransactions'
import { CosmosValidators } from './pages/CosmosValidators'
import { CosmosValidatorDetail } from './pages/CosmosValidatorDetail'
import { CosmosTransactionDetail } from './pages/CosmosTransactionDetail'
import { CosmosExplorerLayout } from './layouts/CosmosExplorerLayout'

const NETWORK_MASCOT_SRC = '/assets/network-mascot.png?v=1'

function OverviewPage() {
  const explorerData = useExplorerData()

  return (
    <ExplorerLayout
      healthState={explorerData.healthState}
      nextFastRefreshAt={explorerData.nextFastRefreshAt}
      averageBlockTimeSeconds={explorerData.data.network?.average_block_time_seconds}
      averageBlockTimeSampleSize={explorerData.data.network?.average_block_time_sample_size}
      averageBlockTimeIntervalsSeconds={explorerData.data.network?.average_block_time_intervals_seconds}
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
      <BlockDetail blockDetail={blockDetail} routeHeight={height} />
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
  const showRefreshCountdown = transactionsPage.pageIndex === 0 && Boolean(transactionsPage.nextRefreshAt)

  return (
    <ExplorerLayout healthState={transactionsPage.healthState} nextFastRefreshAt={transactionsPage.nextRefreshAt} showRefreshCountdown={showRefreshCountdown}>
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

function TokensPage() {
  const tokensPage = useTokensPage()
  useTokensAutoRefresh({
    enabled: tokensPage.pageIndex === 0 && !tokensPage.loading,
    refreshTokens: tokensPage.refreshInBackground,
  })
  return <ExplorerLayout healthState={tokensPage.healthState} showRefreshCountdown={false}>
    <Tokens tokensPage={tokensPage} />
  </ExplorerLayout>
}


function RealmDetailPage() {
  const realmPath = decodeRealmDetailPath()
  const detailState = useRealmDetail(realmPath)

  return (
    <ExplorerLayout healthState={detailState.healthState} showRefreshCountdown={false}>
      <RealmDetail path={realmPath} detailState={detailState} />
    </ExplorerLayout>
  )
}

function ValidatorsPage() {
  const validatorsPage = useValidatorsPage()

  return (
    <ExplorerLayout healthState={validatorsPage.healthState} showRefreshCountdown={false}>
      {(chainId) => <Validators validatorsPage={validatorsPage} chainId={chainId} />}
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
  const path = usePathname()
  const { getNetworkById, networksLoading, networksError } = useSelectedNetwork()

  useEffect(() => {
    if (path.startsWith('/networks/')) return
    document.title = `${networkProfile.projectName} Explorer`
    const descriptionMeta = document.querySelector('meta[name="description"]')
    if (descriptionMeta) descriptionMeta.setAttribute('content', networkProfile.description)
  }, [path])

  const cosmosTxMatch = path.match(/^\/networks\/([^/]+)\/blocks\/([1-9]\d{0,18})\/transactions\/(\d{1,4})\/?$/)
  const cosmosMatch = path.match(/^\/networks\/([^/]+)(?:\/(blocks|transactions|validators)(?:\/([^/]+))?)?\/?$/)
  const cosmosNetworkId = cosmosTxMatch?.[1] || cosmosMatch?.[1]
  if (cosmosNetworkId) {
    const network = getNetworkById(cosmosNetworkId)
    if (networksLoading) return <main className="route-error"><p>Loading network registry…</p></main>
    if (networksError) return <main className="route-error"><h1>Network registry unavailable</h1></main>
    if (!network || network.family !== 'cosmos') return <main className="route-error"><h1>Network not found</h1></main>
    if (cosmosTxMatch) {
      const [, , txHeight, txIndex] = cosmosTxMatch
      if (BigInt(txHeight) > 9223372036854775807n || Number(txIndex) > 9999) return <main className="route-error"><h1>Route not found</h1></main>
      return <CosmosExplorerLayout network={network}><CosmosTransactionDetail network={network} height={txHeight} index={txIndex} /></CosmosExplorerLayout>
    }
    const rawHeight = cosmosMatch[2] === 'blocks' ? cosmosMatch[3] : null
    if (cosmosMatch[2] === 'transactions' && cosmosMatch[3]) return <main className="route-error"><h1>Route not found</h1></main>
    const renderContent = ({ overview, blocks, blockTime }) => rawHeight
      ? (/^[1-9]\d{0,18}$/.test(rawHeight) && BigInt(rawHeight) <= 9223372036854775807n
        ? <CosmosBlockDetail network={network} height={rawHeight} />
        : <p className="cosmos-error">Invalid block height.</p>)
      : cosmosMatch[2] === 'transactions' ? <CosmosTransactions network={network} />
      : cosmosMatch[2] === 'validators' && cosmosMatch[3] ? <CosmosValidatorDetail network={network} operatorAddress={cosmosMatch[3]} />
      : cosmosMatch[2] === 'validators' ? <CosmosValidators network={network} />
      : cosmosMatch[2] === 'blocks' ? <CosmosBlocks network={network} resource={blocks} /> : <CosmosOverview network={network} overview={overview} blocks={blocks} averageBlockSeconds={blockTime.average} />
    return <CosmosExplorerLayout network={network}>{renderContent}</CosmosExplorerLayout>
  }
  if (path.startsWith('/networks/')) return <main className="route-error"><h1>Route not found</h1></main>

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
  if (path === '/tokens' || path === '/tokens/') {
    return <TokensPage />
  }
  if (path === '/realm' || path === '/realm/') {
    return <RealmDetailPage />
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
