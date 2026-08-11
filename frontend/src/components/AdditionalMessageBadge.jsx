export function AdditionalMessageBadge({ messageCount }) {
  if (!Number.isInteger(messageCount) || messageCount <= 1) return null

  return (
    <span className="additional-message-badge" title={`${messageCount} messages total`}>
      +{messageCount - 1}
    </span>
  )
}
