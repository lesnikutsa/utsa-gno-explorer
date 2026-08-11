const transactionTypeVariants = {
  'Contract Call': 'contract-call',
  'Add Package': 'add-package',
  'Run Package': 'run-package',
  'Send Tokens': 'send-tokens',
}

export function transactionTypeVariant(label) {
  return transactionTypeVariants[label] ?? 'other'
}
