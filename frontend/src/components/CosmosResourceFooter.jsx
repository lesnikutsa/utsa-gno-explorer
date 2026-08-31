import { ExternalLinkIcon } from './Icons'

const Link = ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}<ExternalLinkIcon /></a>

export function CosmosResourceFooter() {
  return <footer className="cosmos-footer"><div className="resource-strip" aria-label="Explorer resources"><div className="resource-guides"><small>UTSA Guides</small><div><Link href="https://utsa.gitbook.io/services">English</Link><Link href="https://teletype.media/@lesnik13utsa">Русский</Link></div></div></div><div className="page-footer">Explorer by UTSA</div></footer>
}
