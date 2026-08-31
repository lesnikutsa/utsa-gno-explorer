import { countdownParts, formatAverageBlockTime, formatEstimatedArrival, futureHeightValues } from '../utils/futureBlock'

const Metric = ({ label, children }) => <div><span>{label}</span><strong>{children}</strong></div>

export function FutureBlockCard({ data, height, now }) {
  const eta = data.eta
  const countdown = eta ? countdownParts(eta.estimated_at, now) : null
  const values = futureHeightValues(String(height), data.current_height)
  return <section className="cosmos-card cosmos-block-state"><h2>Block #{values.height} has not been produced yet</h2>
    {countdown && <div className="cosmos-future-countdown" aria-label="Estimated time until block">
      <p>Estimated time until block</p>
      <div className="cosmos-future-countdown__grid">{[['Days', countdown.days], ['Hours', countdown.hours], ['Minutes', countdown.minutes], ['Seconds', countdown.seconds]].map(([label, value]) => <div key={label}><strong>{label === 'Days' ? value.toLocaleString('en-US') : String(value).padStart(2, '0')}</strong><span>{label}</span></div>)}</div>
    </div>}
    <div className="cosmos-detail-summary cosmos-future-metrics"><Metric label="Current height">{data.current_height.toLocaleString('en-US')}</Metric><Metric label="Blocks remaining">{values.remaining}</Metric><Metric label="Average block time">{eta ? formatAverageBlockTime(eta.average_block_seconds) : '—'}</Metric><Metric label="Estimated arrival">{eta ? formatEstimatedArrival(eta.estimated_at) : '—'}</Metric></div>
    {eta ? <p className="cosmos-future-note muted">Estimate based on recent network block production.<br />Actual arrival time may vary as block speed changes.</p> : <p className="cosmos-future-unavailable">Estimated arrival is temporarily unavailable.</p>}
  </section>
}
