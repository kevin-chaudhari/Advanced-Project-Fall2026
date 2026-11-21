import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { cx } from '../components/ui'
import { DATASETS } from '../state/DiagnosticsContext'
import { getFleet } from '../services/api'

/*
 * Fleet analytics (Agent-Viz): patterns across many diagnoses rather than one trace.
 * Every number comes from GET /trace-insights/fleet/summary.
 */

const C = { auto: '#78866B', review: '#C18D4D', grid: '#E5DED1', ink: '#4A453D', accent: '#6E5A3E' }
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const SEV = { high: 'text-danger-700', medium: 'text-warning-700', info: 'text-muted' }

function Tile({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 text-[22px] font-semibold tabular-nums text-ink">{value}</p>
      {hint && <p className="text-[11.5px] text-muted">{hint}</p>}
    </div>
  )
}

function Panel({ title, subtitle, children, className }) {
  return (
    <section className={cx('rounded-xl border border-line bg-surface p-4', className)}>
      <h2 className="text-[13.5px] font-semibold text-ink">{title}</h2>
      {subtitle && <p className="mt-0.5 text-[12px] text-muted">{subtitle}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

/** answer × signal: share of that answer's traces where the signal fired */
function Heatmap({ heat }) {
  const { answers, signals, cells, answer_counts: counts } = heat
  if (!answers.length) return <p className="text-[12.5px] text-muted">No traces with step recording yet.</p>
  return (
    <div className="overflow-x-auto">
      <table className="text-[11.5px]">
        <thead><tr><th />{signals.map((s) => <th key={s} className="px-0.5 pb-1 align-bottom font-normal text-muted"><span className="block max-h-[120px] whitespace-nowrap [writing-mode:vertical-rl] rotate-180">{s.replace(/_/g, ' ')}</span></th>)}</tr></thead>
        <tbody>
          {answers.map((a) => (
            <tr key={a}>
              <td className="whitespace-nowrap pr-2 font-medium text-ink">{a}</td>
              {signals.map((s) => {
                const n = cells[a]?.[s] || 0
                const total = Object.values(cells[a] || {}).length ? Math.max(...Object.values(cells[a])) : 1
                const share = counts[a] ? n / Math.max(total, 1) : 0
                return <td key={s} className="p-0.5"><span title={`${a} · ${s}: ${n}`} className="grid h-7 w-7 place-items-center rounded-[3px] tabular-nums text-[10.5px]"
                  style={{ background: n ? `rgba(193,141,77,${0.15 + 0.85 * share})` : '#F1ECE1', color: share > 0.6 ? '#FFFCF5' : '#4A453D' }}>{n || ''}</span></td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function FleetAnalyticsPage() {
  const nav = useNavigate()
  const [origin, setOrigin] = useState('live')
  const [dataset, setDataset] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let live = true
    setData(null); setError(null)
    getFleet({ origin, dataset: dataset || null }).then((d) => live && setData(d)).catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [origin, dataset])
  const scatter = useMemo(() => ({
    auto: (data?.scatter || []).filter((p) => p.review === 'AUTO_RESOLVE'),
    review: (data?.scatter || []).filter((p) => p.review !== 'AUTO_RESOLVE'),
  }), [data])

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1280px] space-y-4 px-4 py-5 sm:px-6">
        <header className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-[20px] font-semibold text-ink">Fleet analytics</h1>
            <p className="text-[12.5px] text-muted">Patterns across many diagnoses: how often the council needs a person, which checks fire, and for which answers.</p>
          </div>
          <select value={dataset} onChange={(e) => setDataset(e.target.value)} aria-label="Dataset" className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px]">
            <option value="">All datasets</option>{DATASETS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
          </select>
          <select value={origin} onChange={(e) => setOrigin(e.target.value)} aria-label="Which traces" className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px]">
            <option value="live">Real diagnoses</option><option value="experiment">Experiment runs</option><option value="all">Both</option>
          </select>
        </header>

        {error && <p role="alert" className="text-[12.5px] text-danger-700">{error}</p>}
        {!data && !error && <p className="flex items-center gap-2 text-[13px] text-muted"><Loader2 size={14} className="animate-spin" />Aggregating…</p>}
        {data && !data.total && <p className="text-[13px] text-muted">No traces match these filters.</p>}
        {data?.total > 0 && <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Tile label="Diagnoses" value={data.total} hint={`${data.with_snapshot} with step recording`} />
            <Tile label="Sent to human review" value={pct(data.review_rate)} hint={`${data.requires_review} of ${data.total}`} />
            <Tile label="Average confidence" value={pct(data.avg_confidence)} hint="recorded score, not calibrated" />
            <Tile label="Reviewer decisions" value={Object.values(data.reviews).reduce((a, b) => a + b, 0)}
              hint={Object.entries(data.reviews).map(([k, v]) => `${v} ${k}`).join(' · ') || 'none yet'} />
            <Tile label="Robustness checks" value={Object.values(data.robustness).reduce((a, b) => a + b, 0)}
              hint={Object.entries(data.robustness).map(([k, v]) => `${v} ${k}`).join(' · ') || 'none yet'} />
          </section>
          {data.with_snapshot < data.total && (
            <p className="rounded-md border border-line bg-well/60 px-3 py-1.5 text-[12px] text-muted">
              Signals, gaps, margin and the scatter use the {data.with_snapshot} diagnoses made since step recording was added; older traces count only toward volume, review rate and confidence.
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Confidence vs lead over the runner-up" subtitle="Each dot is one diagnosis (click to open). Lines: the review gate's 65% confidence and 0.15 lead rules.">
              <div className="h-[260px]">
                <ResponsiveContainer>
                  <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
                    <CartesianGrid stroke={C.grid} />
                    <XAxis type="number" dataKey="margin" name="Lead" domain={[0, 'auto']} tick={{ fontSize: 11, fill: C.ink }} label={{ value: 'lead over runner-up', position: 'insideBottom', offset: -10, fontSize: 11, fill: C.ink }} />
                    <YAxis type="number" dataKey="confidence" name="Confidence" domain={[0, 1]} tickFormatter={pct} tick={{ fontSize: 11, fill: C.ink }} width={40} />
                    <ReferenceLine y={0.65} stroke={C.ink} strokeDasharray="4 3" />
                    <ReferenceLine x={0.15} stroke={C.ink} strokeDasharray="4 3" />
                    <Tooltip cursor={{ strokeDasharray: '3 3' }} formatter={(v, n) => (n === 'Confidence' ? pct(v) : Number(v).toFixed(2))}
                      labelFormatter={() => ''} content={({ payload }) => payload?.[0] ? (
                        <div className="rounded-md border border-line bg-surface px-2 py-1 text-[11.5px] shadow-lift"><b>{payload[0].payload.answer}</b><br />{pct(payload[0].payload.confidence)} · lead {payload[0].payload.margin.toFixed(2)}</div>) : null} />
                    <Legend verticalAlign="top" height={24} iconSize={8} wrapperStyle={{ fontSize: 11.5 }} />
                    <Scatter name="Auto-resolved" data={scatter.auto} fill={C.auto} onClick={(p) => nav(`/traces/${p.trace_id}`)} cursor="pointer" />
                    <Scatter name="Human review" data={scatter.review} fill={C.review} onClick={(p) => nav(`/traces/${p.trace_id}`)} cursor="pointer" />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel title="Diagnoses per day" subtitle="Auto-resolved vs sent to a person.">
              <div className="h-[260px]">
                <ResponsiveContainer>
                  <BarChart data={data.by_day} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke={C.grid} vertical={false} />
                    <XAxis dataKey="day" tick={{ fontSize: 11, fill: C.ink }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: C.ink }} width={32} />
                    <Tooltip contentStyle={{ fontSize: 12 }} />
                    <Legend verticalAlign="top" height={24} iconSize={8} wrapperStyle={{ fontSize: 11.5 }} />
                    <Bar dataKey="auto" name="Auto-resolved" stackId="a" fill={C.auto} />
                    <Bar dataKey="review" name="Human review" stackId="a" fill={C.review} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <Panel title="How often each check fires" subtitle={`Share of the ${data.with_snapshot} diagnoses with step recording.`}>
              {data.signals.length ? (
                <ul className="space-y-1.5">
                  {data.signals.map((s) => (
                    <li key={s.id} className="grid grid-cols-[minmax(0,1fr)_120px_44px] items-center gap-2 text-[12.5px]">
                      <span className="truncate"><span className={cx('font-medium', SEV[s.severity])}>{s.title}</span>{s.kind === 'gap' && <span className="ml-1 text-[10.5px] uppercase text-muted">gap</span>}</span>
                      <span className="h-2 rounded-full bg-well"><span className="block h-full rounded-full bg-warning-500" style={{ width: `${s.rate * 100}%` }} /></span>
                      <span className="text-right tabular-nums text-muted">{pct(s.rate)}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-[12.5px] text-muted">No checks have fired yet.</p>}
            </Panel>
            <Panel title="Which answers trip which checks" subtitle="Count of diagnoses per answer where the check fired (darker = more common for that answer).">
              <Heatmap heat={data.heatmap} />
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="By diagnosis">
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]">
                  <thead className="text-left text-muted"><tr><th className="py-1 pr-3 font-medium">Answer</th><th className="py-1 pr-3 font-medium">Count</th><th className="py-1 pr-3 font-medium">Human review</th><th className="py-1 pr-3 font-medium">Avg confidence</th><th className="py-1 font-medium">Avg lead</th></tr></thead>
                  <tbody>{data.by_answer.map((a) => (
                    <tr key={a.answer} className="border-t border-line"><td className="py-1 pr-3 text-ink">{a.answer}</td><td className="py-1 pr-3 tabular-nums">{a.count}</td>
                      <td className="py-1 pr-3 tabular-nums">{pct(a.review_rate)}</td><td className="py-1 pr-3 tabular-nums">{pct(a.avg_confidence)}</td>
                      <td className="py-1 tabular-nums">{a.avg_margin == null ? '—' : a.avg_margin.toFixed(2)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </Panel>
            <Panel title="Confidence distribution">
              <div className="h-[220px]">
                <ResponsiveContainer>
                  <BarChart data={data.confidence_hist} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke={C.grid} vertical={false} />
                    <XAxis dataKey="bin" tick={{ fontSize: 10.5, fill: C.ink }} interval={0} angle={-30} textAnchor="end" height={44} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: C.ink }} width={32} />
                    <Tooltip contentStyle={{ fontSize: 12 }} />
                    <Bar dataKey="count" name="Diagnoses" fill={C.accent} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>
        </>}
      </div>
    </div>
  )
}
