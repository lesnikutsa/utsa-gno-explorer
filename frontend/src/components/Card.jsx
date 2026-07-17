export function Card({ eyebrow, value, meta, icon, loading = false }) {
  return (
    <article className="card status-card">
      <div className="status-card__heading">
        <span className="eyebrow">{eyebrow}</span>
        <span className="status-card__icon" aria-hidden="true">{icon}</span>
      </div>
      <div className={loading ? 'status-card__value skeleton' : 'status-card__value'}>{loading ? 'Loading' : value}</div>
      <div className="status-card__meta">{meta}</div>
    </article>
  )
}
