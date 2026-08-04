export function getRealmDetailViewModel(response) {
  const source = response.source
  const item = response.item
  return {
    source,
    item,
    namespaceKey: response.namespace_key,
    application: response.application,
    path: item.path,
    kind: item.kind,
    rpcVisible: item.rpc_visible,
    callIndexComplete: source.call_index_complete,
    overview: {
      directCalls: item.call_count,
      successRate: item.success_rate,
      successfulCalls: item.successful_call_count,
      failedCalls: item.failed_call_count,
      unknownResultCalls: item.unknown_result_call_count,
      firstSeenHeight: item.first_seen_height,
      lastActivityAt: item.last_activity_at,
      lastActivityHeight: item.last_activity_height,
      deployHeight: item.deploy_height,
      deployTxIndex: item.deploy_tx_index,
      deployerAddress: item.deployer_address,
      indexedHeight: source.indexed_height,
    },
    sourceStatus: {
      catalogObservedHeight: source.catalog_observed_height,
      indexedHeight: source.indexed_height,
      callIndexFromHeight: source.call_index_from_height,
      callIndexThroughHeight: source.call_index_through_height,
      callIndexComplete: source.call_index_complete,
    },
  }
}

export function realmCallsPathForDetail(response) {
  const viewModel = getRealmDetailViewModel(response)
  if (viewModel.item.kind !== 'realm') return null
  if (viewModel.source.call_index_complete !== true) return null
  return viewModel.item.path
}

export function getRealmCallViewModel(row) {
  return {
    blockHeight: row.block_height,
    txIndex: row.tx_index,
    messageIndex: row.message_index,
    blockTime: row.block_time,
    txHash: row.tx_hash,
    callerAddress: row.caller_address,
    functionName: row.function_name,
    executionStatus: row.execution_status,
    gasWanted: row.gas_wanted,
    gasUsed: row.gas_used,
  }
}
