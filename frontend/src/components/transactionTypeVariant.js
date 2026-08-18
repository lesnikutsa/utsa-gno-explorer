const transactionTypeVariants = {
  'Contract Call': 'contract-call',
  'NFT Mint': 'nft',
  'NFT Transfer': 'nft',
  'NFT Approval': 'nft',
  'NFT Burn': 'nft',
  'GRC20 Transfer': 'grc20',
  'GRC20 Approval': 'grc20',
  'Coin Transfer': 'coin-transfer',
  'Deployment': 'deployment',
  'Package Run': 'package-run',
}

export function transactionTypeVariant(label) {
  return transactionTypeVariants[label] ?? 'other'
}
