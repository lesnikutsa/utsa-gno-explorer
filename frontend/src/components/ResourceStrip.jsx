export function ResourceStrip({ illustrationSrc = null }) {
  return (
    <section className="resource-strip" aria-label="Explorer resources">
      <div className="resource-strip__asset" aria-hidden="true">
        {illustrationSrc ? <img src={illustrationSrc} alt="" /> : <span>UTSA tool art</span>}
      </div>
      <div className="resource-item"><div><small>Community tool</small><strong>Telegram Bot</strong></div></div>
      <span className="resource-divider" />
      <div className="resource-guides">
        <small>Guides</small>
        <div><strong>English Guides</strong><strong>Русские гайды</strong></div>
      </div>
    </section>
  )
}
