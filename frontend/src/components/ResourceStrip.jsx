import { ExternalLinkIcon } from './Icons'

const ExternalLink = ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}<ExternalLinkIcon /></a>

export function ResourceStrip() {
  return (
    <section className="resource-strip" aria-label="Explorer resources">
      <div className="resource-item"><small>Community tool</small><ExternalLink href="https://t.me/UTSAGNOTest13Bot">Telegram Bot</ExternalLink></div>
      <span className="resource-divider" />
      <div className="resource-guides">
        <small>Guides</small>
        <div><ExternalLink href="https://utsa.gitbook.io/services/testnet/gno.land">English</ExternalLink><ExternalLink href="https://teletype.in/@lesnik13utsa/65wu7A2kPfo">Русский</ExternalLink></div>
      </div>
      <span className="resource-divider" />
      <div className="resource-item"><small>Community Resources</small><ExternalLink href="https://cumulo.pro/services/gnoland_testnet/resources">Cumulo</ExternalLink></div>
    </section>
  )
}
