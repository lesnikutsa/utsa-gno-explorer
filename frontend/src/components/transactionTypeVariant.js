const transactionTypeVariants = {
  'Contract Call': 'contract-call',
  'NFT Mint': 'nft',
  'NFT Transfer': 'nft',
  'NFT Approval': 'nft',
  'NFT Burn': 'nft',
  'Token Transfer': 'token',
  'Token Approval': 'token',
  'Transfer': 'transfer',
  'Deployment': 'deployment',
  'Package Run': 'package-run',
}

export function transactionTypeVariant(label) {
  return transactionTypeVariants[label] ?? 'other'
}
