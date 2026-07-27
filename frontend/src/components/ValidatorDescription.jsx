import { parseValidatorDescription, splitValidatorDescriptionLinks } from '../utils/validatorDescription'

function DescriptionContent({ content }) {
  return splitValidatorDescriptionLinks(content).map((part, index) => part.type === 'link' ? (
    <a
      className="validator-description__link"
      href={part.href}
      target="_blank"
      rel="noopener noreferrer"
      key={`${index}-${part.value}`}
    >
      {part.value}
    </a>
  ) : <span key={`${index}-${part.value}`}>{part.value}</span>)
}

export function ValidatorDescription({ description }) {
  const parsed = parseValidatorDescription(description)

  if (parsed.type === 'empty') return <span className="validator-description__empty">—</span>
  if (parsed.type === 'plain') {
    return <p className="validator-description__content"><DescriptionContent content={parsed.content} /></p>
  }

  return (
    <div className="validator-description__structured">
      {parsed.preamble && <p className="validator-description__content"><DescriptionContent content={parsed.preamble} /></p>}
      <dl className="validator-description">
        {parsed.sections.map((section, index) => (
          <div className="validator-description__section" key={`${index}-${section.label}`}>
            <dt className="validator-description__heading">{section.label}</dt>
            <dd className="validator-description__content"><DescriptionContent content={section.content} /></dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
