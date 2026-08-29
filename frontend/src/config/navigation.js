import { NetworkCapability } from './networkRegistry'
import { BlocksIcon, GovernanceIcon, HomeIcon, RealmsIcon, TokensIcon, TransactionsIcon, ValidatorsIcon } from '../components/Icons'

export const navigationItems = Object.freeze([
  { label: 'Overview', Icon: HomeIcon, href: '/', capability: NetworkCapability.OVERVIEW },
  { label: 'Blocks', Icon: BlocksIcon, href: '/blocks', capability: NetworkCapability.BLOCKS },
  { label: 'Transactions', Icon: TransactionsIcon, href: '/transactions', capability: NetworkCapability.TRANSACTIONS },
  { label: 'Realms', Icon: RealmsIcon, href: '/realms', capability: NetworkCapability.REALMS },
  { label: 'Tokens', Icon: TokensIcon, href: '/tokens', capability: NetworkCapability.TOKENS },
  { label: 'Validators', Icon: ValidatorsIcon, href: '/validators', capability: NetworkCapability.VALIDATORS },
  { label: 'Governance', Icon: GovernanceIcon, href: '/governance', capability: NetworkCapability.GOVERNANCE },
])
