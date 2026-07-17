export function Card({ eyebrow, value, meta, icon: Icon, loading = false, tone = '' }) {
  return (
    <article className="card status-card">
      <div className="status-card__heading">
        <span className="eyebrow">{eyebrow}</span>
        {Icon && <span className="status-card__icon"><Icon /></span>}
      </div>
      <div className={loading ? 'status-card__value skeleton' : `status-card__value ${tone ? `status-card__value--${tone}` : ''}`}>{loading ? 'Loading' : value}</div>
      {meta && <div className="status-card__meta">{meta}</div>}
    </article>
  )
}
