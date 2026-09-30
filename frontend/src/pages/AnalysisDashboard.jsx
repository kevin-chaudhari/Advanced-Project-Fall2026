import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid, LineChart, Line } from 'recharts'
import AppShell from '../components/AppShell'
import { Card, StatTile, SourceBadge, Empty, pct, fmtNum, cx } from '../components/ui'
import { getDatasetSummary, getEvaluation, getAnalyses } from '../services/api'

const C_REAL = '#2563EB'
const C_SYN = '#0891B2'
const C_BASE = '#94A3B8'
const axis = { fontSize: 11, fill: '#64748B' }
const grid = <CartesianGrid stroke="#EEF2F7" vertical={false} />

function TooltipBox({ active, payload, label, fmt = (v) => v }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 shadow-lift text-[12px]">
      <div className="font-semibold text-ink mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-ink">
          <span className="w-2 h-2 rounded-sm" style={{ background: p.color }} />{p.name}: <b className="tabular-nums">{fmt(p.value)}</b>
        </div>
      ))}
    </div>
  )
}

const METRICS = [
  ['diagnostic_accuracy', 'Diagnostic accuracy', 'pct', true],
  ['accuracy_real_holdout', 'Accuracy — held-out REAL records', 'pct', true],
  ['accuracy_synthetic', 'Accuracy — synthetic scenarios', 'pct', true],
  ['hallucination_rate', 'Unsupported numeric claims (share)', 'pct', false],
  ['missing_sensor_fabrication_rate', 'Missing-sensor fabrication rate', 'pct', false],
  ['evidence_grounding', 'Evidence grounding of cited items', 'pct', true],
  ['retrieval_precision_at5', 'Retrieval precision@5', 'pct', true],
  ['retrieval_hit_at5', 'Retrieval hit@5', 'pct', true],
  ['ambiguity_recall', 'Ambiguous cases sent to review', 'pct', true],
  ['false_review_rate', 'Clear cases sent to review', 'pct', false],
  ['accuracy_when_auto_resolved', 'Accuracy when auto-resolved', 'pct', true],
  ['errors_caught_by_review', 'Wrong answers caught by the review gate', 'pct', true],
  ['latency_ms_median', 'Median latency (ms)', 'num', false],
]
const RUN_LABEL = {
  baseline: 'Original pipeline (baseline)', harness_real: 'Harness · REAL', harness_synthetic: 'Harness · SYNTHETIC',
  harness_combined: 'Harness · COMBINED', ablation_no_feedback_combined: 'Harness · COMBINED, no feedback loop',
}

export default function AnalysisDashboard() {
  const [summary, setSummary] = useState(null)
  const [evalRes, setEvalRes] = useState(null)
  const [history, setHistory] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => {
    getDatasetSummary('afrb').then(setSummary).catch((e) => setErr(e.response?.data?.detail || e.message))
    getEvaluation().then(setEvalRes).catch(() => setEvalRes({}))
    getAnalyses(20).then((d) => setHistory(d.records || [])).catch(() => {})
  }, [])

  const real = summary?.partitions?.real
  const syn = summary?.partitions?.synthetic

  const labelRows = useMemo(() => {
    if (!summary) return []
    const labels = new Set([...Object.keys(real?.label_distribution || {}), ...Object.keys(syn?.label_distribution || {})])
    return [...labels].map((l) => ({ label: l, REAL: real?.label_distribution?.[l] || 0, SYNTHETIC: syn?.label_distribution?.[l] || 0 }))
      .sort((a, b) => b.REAL + b.SYNTHETIC - (a.REAL + a.SYNTHETIC))
  }, [summary])

  const missing = (real?.missing_values || 0) + (syn?.missing_values || 0)
  const dups = (real?.duplicate_records || 0) + (syn?.duplicate_records || 0)
  const classes = labelRows.length
  const components = Object.keys(syn?.components || {}).filter((c) => c !== 'None').length

  const runs = evalRes ? Object.keys(RUN_LABEL).filter((k) => evalRes[k]) : []
  const chartRows = evalRes?.baseline ? [
    ['diagnostic_accuracy', 'Accuracy'], ['accuracy_real_holdout', 'Accuracy (real hold-out)'], ['evidence_grounding', 'Evidence grounding'],
    ['retrieval_precision_at5', 'Retrieval P@5'], ['hallucination_rate', 'Unsupported claims'], ['missing_sensor_fabrication_rate', 'Missing-sensor fabrication'],
  ].map(([k, name]) => ({ name, Baseline: evalRes.baseline.summary[k], 'Harness (combined)': evalRes.harness_combined?.summary?.[k], 'Harness (real only)': evalRes.harness_real?.summary?.[k] })) : []

  return (
    <AppShell>
      <header className="h-14 border-b border-line bg-white px-6 flex items-center"><h1 className="text-[15px] font-semibold">Data & evaluation</h1></header>
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {err && <div className="card p-4 text-sm text-danger-700">{err}</div>}

        {/* Data quality panel */}
        <Card title="Data quality — AFRB knowledge base" subtitle="Computed live from the loaded records; synthetic rows are a separate, labelled partition">
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
            <StatTile label="Total records" value={fmtNum(summary?.totals?.records, 0)} />
            <StatTile label="Real records" value={fmtNum(summary?.totals?.real, 0)} accent="text-primary-700" />
            <StatTile label="Synthetic records" value={fmtNum(summary?.totals?.synthetic, 0)} accent="text-secondary-700" />
            <StatTile label="Failure classes" value={classes || '—'} hint="incl. Normal Operation" />
            <StatTile label="Missing values" value={fmtNum(missing, 0)} hint="kept missing, never imputed" />
            <StatTile label="Duplicate records" value={fmtNum(dups, 0)} />
            <StatTile label="Components" value={components || '—'} hint="synthetic metadata" />
            <StatTile label="Sensor channels" value={summary?.sensors?.length ?? '—'} />
          </div>
          {summary?.sensors && (
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead className="text-muted text-left"><tr><th className="py-1 font-medium">Sensor coverage</th>{summary.sensors.map((s) => <th key={s.sensor} className="font-medium">{s.label}</th>)}</tr></thead>
                <tbody>
                  {[['real', real], ['synthetic', syn]].map(([k, p]) => p && (
                    <tr key={k} className="border-t border-line"><td className="py-1.5"><SourceBadge source={k} size="xs" /></td>
                      {summary.sensors.map((s) => <td key={s.sensor} className={cx('tabular-nums', p.sensor_coverage?.[s.sensor] < 1 && 'text-warning-700')}>{pct(p.sensor_coverage?.[s.sensor], 1)}</td>)}
                    </tr>))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Composition + failure distribution */}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Failure-mode distribution" subtitle="Records per label, REAL vs SYNTHETIC — synthetic data fills classes the real data lacks">
            {!labelRows.length ? <Empty>Loading…</Empty> : (
              <ResponsiveContainer width="100%" height={Math.max(260, labelRows.length * 30)}>
                <BarChart data={labelRows} layout="vertical" margin={{ left: 40, right: 16 }} barGap={2}>
                  <CartesianGrid stroke="#EEF2F7" horizontal={false} />
                  <XAxis type="number" tick={axis} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="label" tick={axis} width={150} axisLine={false} tickLine={false} />
                  <Tooltip content={<TooltipBox fmt={(v) => v.toLocaleString()} />} cursor={{ fill: '#F1F5F9' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="REAL" fill={C_REAL} radius={[0, 4, 4, 0]} barSize={9} />
                  <Bar dataKey="SYNTHETIC" fill={C_SYN} radius={[0, 4, 4, 0]} barSize={9} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
          <Card title="Synthetic coverage" subtitle="Scenario families, severity and components generated to fill the gap analysis">
            {!syn ? <Empty>No synthetic partition loaded.</Empty> : (
              <div className="space-y-5">
                {[['Scenario family', syn.scenarios], ['Severity', syn.severity], ['Component', syn.components]].map(([t, d]) => (
                  <div key={t}>
                    <div className="eyebrow mb-1.5">{t}</div>
                    <div className="space-y-1">
                      {Object.entries(d || {}).slice(0, 10).map(([k, v]) => {
                        const max = Math.max(...Object.values(d))
                        return (
                          <div key={k} className="flex items-center gap-2 text-[12px]" title={`${k}: ${v}`}>
                            <span className="w-36 truncate text-ink">{k}</span>
                            <div className="flex-1 h-2 bg-slate-100 rounded-r"><div className="h-full rounded-r" style={{ width: `${(v / max) * 100}%`, background: C_SYN }} /></div>
                            <span className="w-12 text-right tabular-nums text-muted">{v}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
                {summary?.synthetic_validation?.knowledge_base && (
                  <p className="text-[11px] text-muted">Automatic validation: {summary.synthetic_validation.knowledge_base.all_checks_passed ? 'all range, duplicate, provenance and relationship checks passed' : 'some checks failed'} (generator {summary.synthetic_validation.generator_version}).</p>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Sensor distributions (small multiples) */}
        {summary?.sensors && (
          <Card title="Sensor distributions" subtitle="Share of each partition per value bin — REAL vs SYNTHETIC (normalised, since partition sizes differ)">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {summary.sensors.map((s) => {
                const hr = real?.histograms?.[s.sensor] || [], hs = syn?.histograms?.[s.sensor] || []
                const tr = hr.reduce((a, b) => a + b, 0) || 1, ts = hs.reduce((a, b) => a + b, 0) || 1
                const [lo, hi] = s.range
                const data = hr.map((v, i) => ({ bin: fmtNum(lo + ((hi - lo) * (i + 0.5)) / hr.length, 2), REAL: v / tr, SYNTHETIC: (hs[i] || 0) / ts }))
                return (
                  <div key={s.sensor}>
                    <div className="text-[12px] font-semibold text-ink">{s.label} <span className="text-muted font-normal">{s.unit}</span></div>
                    <ResponsiveContainer width="100%" height={120}>
                      <LineChart data={data} margin={{ top: 6, right: 6, left: -24, bottom: 0 }}>
                        {grid}
                        <XAxis dataKey="bin" tick={{ ...axis, fontSize: 9 }} interval={4} axisLine={false} tickLine={false} />
                        <YAxis tick={{ ...axis, fontSize: 9 }} tickFormatter={(v) => `${Math.round(v * 100)}%`} axisLine={false} tickLine={false} />
                        <Tooltip content={<TooltipBox fmt={(v) => pct(v, 1)} />} />
                        <Line type="monotone" dataKey="REAL" stroke={C_REAL} strokeWidth={2} dot={false} />
                        <Line type="monotone" dataKey="SYNTHETIC" stroke={C_SYN} strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )
              })}
            </div>
            <div className="flex gap-4 text-[12px] text-muted mt-2"><span className="flex items-center gap-1.5"><span className="w-3 h-0.5" style={{ background: C_REAL }} />REAL</span><span className="flex items-center gap-1.5"><span className="w-3 h-0.5" style={{ background: C_SYN }} />SYNTHETIC</span></div>
          </Card>
        )}

        {/* Signatures table */}
        {real?.sensor_medians_by_label && (
          <Card title="Sensor signatures by failure mode" subtitle="Median reading per label (combined knowledge base; used by the signature-fit analysis)">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead className="text-muted text-left"><tr><th className="py-1 font-medium">Failure mode</th><th className="font-medium">Source</th>{summary.sensors.map((s) => <th key={s.sensor} className="font-medium">{s.label}</th>)}</tr></thead>
                <tbody>
                  {[['real', real], ['synthetic', syn]].flatMap(([src, p]) => Object.entries(p?.sensor_medians_by_label || {}).map(([lab, med]) => (
                    <tr key={src + lab} className="border-t border-line"><td className="py-1.5 pr-2 text-ink">{lab}</td><td><SourceBadge source={src} size="xs" /></td>
                      {summary.sensors.map((s) => <td key={s.sensor} className="tabular-nums">{fmtNum(med[s.sensor], 2)}</td>)}</tr>)))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {/* Evaluation */}
        <Card title="Before / after evaluation" subtitle="Same 246 held-out scenarios (176 synthetic with known ground truth + 70 real AFRB records excluded from retrieval), same scoring code">
          {!runs.length ? <Empty>No benchmark results found. Run evaluation/benchmark.py.</Empty> : (
            <div className="space-y-5">
              {chartRows.length > 0 && (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={chartRows} margin={{ left: -10, right: 10 }} barGap={2}>
                    {grid}
                    <XAxis dataKey="name" tick={axis} axisLine={false} tickLine={false} interval={0} />
                    <YAxis tick={axis} tickFormatter={(v) => `${Math.round(v * 100)}%`} domain={[0, 1]} axisLine={false} tickLine={false} />
                    <Tooltip content={<TooltipBox fmt={(v) => pct(v, 1)} />} cursor={{ fill: '#F1F5F9' }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="Baseline" fill={C_BASE} radius={[4, 4, 0, 0]} barSize={14} />
                    <Bar dataKey="Harness (real only)" fill={C_REAL} radius={[4, 4, 0, 0]} barSize={14} />
                    <Bar dataKey="Harness (combined)" fill={C_SYN} radius={[4, 4, 0, 0]} barSize={14} />
                  </BarChart>
                </ResponsiveContainer>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead className="text-muted text-left"><tr><th className="py-1 font-medium">Metric</th>{runs.map((r) => <th key={r} className="font-medium pr-3">{RUN_LABEL[r]}</th>)}</tr></thead>
                  <tbody>{METRICS.map(([k, name, kind]) => (
                    <tr key={k} className="border-t border-line"><td className="py-1.5 pr-3 text-ink">{name}</td>
                      {runs.map((r) => { const v = evalRes[r].summary?.[k]; return <td key={r} className="tabular-nums pr-3">{v == null ? '—' : kind === 'pct' ? pct(v, 1) : fmtNum(v, 0)}</td> })}
                    </tr>))}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-muted">{evalRes.baseline?.llm_available === false ? 'Both systems ran without an LLM (their offline paths): the original pipeline used its rule-based mock responses, the harness its deterministic agents. LLM-mode quality was not benchmarked here.' : ''} Baseline ambiguity/false-review rates are 100% because the original pipeline flagged every case.</p>
            </div>
          )}
        </Card>

        {/* History */}
        <Card title="Recent diagnoses" subtitle="Stored analyses (SQLite)">
          {!history.length ? <Empty>No stored analyses yet.</Empty> : (
            <table className="w-full text-[12px]">
              <thead className="text-muted text-left"><tr><th className="py-1 font-medium">When</th><th className="font-medium">Question</th><th className="font-medium">Diagnosis</th><th className="font-medium">Confidence</th></tr></thead>
              <tbody>{history.map((h) => (
                <tr key={h.id} className="border-t border-line align-top"><td className="py-1.5 pr-3 text-muted whitespace-nowrap">{h.created_at?.slice(0, 16).replace('T', ' ')}</td>
                  <td className="pr-3 max-w-xs truncate" title={h.question}>{h.question}</td><td className="pr-3 max-w-md truncate" title={h.final_diagnosis}>{h.final_diagnosis}</td><td className="tabular-nums">{pct(h.confidence)}</td></tr>))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </AppShell>
  )
}
