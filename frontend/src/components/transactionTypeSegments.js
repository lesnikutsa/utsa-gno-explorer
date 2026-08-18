const transactionTypeSegments = {
  'GRC20 Transfer': { prefix: 'GRC20', action: 'Transfer' },
  'GRC20 Approval': { prefix: 'GRC20', action: 'Approval' },
  'NFT Mint': { prefix: 'NFT', action: 'Mint' },
  'NFT Transfer': { prefix: 'NFT', action: 'Transfer' },
  'NFT Approval': { prefix: 'NFT', action: 'Approval' },
  'NFT Burn': { prefix: 'NFT', action: 'Burn' },
}

export function transactionTypeSegment(label) {
  return transactionTypeSegments[label] ?? null
}
