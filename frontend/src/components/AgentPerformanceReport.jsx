import { useEffect, useState, useMemo } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis, RadarChart, PolarGrid, PolarAngleAxis,
  PolarRadiusAxis, Radar, LineChart, Line,
} from 'recharts'
import {
  Activity, Award, BarChart2, Brain, RefreshCw,
  Shield, Star, Target, TrendingDown, TrendingUp, Trophy, Zap,
} from 'lucide-react'
import { getAgentReport } from '../services/api'

// ── Agent colour / emoji map ──────────────────────────────────────────────────
const AGENT_META = {
  diagnostic_expert:        { label: 'Diagnostic Expert',     short: 'Expert',      emoji: '🧠', color: '#5b7fff' },
  pattern_agent:            { label: 'Pattern Recognition',   short: 'Pattern',     emoji: '🔍', color: '#f472b6' },
  aggressive_agent:         { label: 'Aggressive Decision',   short: 'Aggressive',  emoji: '⚡', color: '#ffd93d' },
  verification:             { label: 'Verification Analyst',  short: 'Verify',      emoji: '✅', color: '#39ff14' },
  ambiguity:                { label: 'Ambiguity Detection',   short: 'Ambiguity',   emoji: '🎯', color: '#00f5ff' },
  human_review_coordinator: { label: 'HRC / Coordinator',    short: 'HRC',         emoji: '🏁', color: '#bf5fff' },
}
const AGENT_KEYS = Object.keys(AGENT_META)

const METRIC_LABELS = {
  faithfulness_score: 'Faithfulness',
  reasoning_score:    'Reasoning',
  agreement_score:    'Agreement',
  coverage_score:     'Coverage',
  reliability_score:  'Reliability',
}

const METRIC_ICONS = {
  faithfulness_score: '🔒',
  reasoning_score:    '🧠',
  agreement_score:    '🤝',
  coverage_score:     '🗺️',
  reliability_score:  '⚡',
}

const TRAIT_ICONS = {
  speed:                '🏎️',
  analytical_depth:     '🔬',
  evidence_rigor:       '📋',
  pattern_matching:     '📡',
  uncertainty_handling: '⚖️',
  decision_confidence:  '🎯',
  consensus_building:   '🤝',
  risk_awareness:       '🛡️',
}

const METRIC_COLORS = {
  faithfulness_score: '#5b7fff',
  reasoning_score:    '#f472b6',
  agreement_score:    '#39ff14',
  coverage_score:     '#00f5ff',
  reliability_score:  '#bf5fff',
}

function pct(v) { return Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100) }

function VerdictBadge({ verdict }) {
  const v = String(verdict || '').toLowerCase()
  if (v.includes('strong'))
    return <span className="rounded-full border border-emerald-400/50 bg-emerald-500/15 px-3 py-1 text-xs font-bold text-emerald-300">{verdict}</span>
  if (v.includes('moderate'))
    return <span className="rounded-full border border-yellow-400/50 bg-yellow-500/15 px-3 py-1 text-xs font-bold text-yellow-200">{verdict}</span>
  return <span className="rounded-full border border-red-400/50 bg-red-500/15 px-3 py-1 text-xs font-bold text-red-300">{verdict}</span>
}

// ── 1. Trait score radar for a single agent (1-10 scale) ─────────────────────
function TraitRadar({ traitScores, traitLabels, color }) {
  const data = Object.entries(traitScores || {}).map(([key, val]) => ({
    subject: (traitLabels?.[key] || key).replace(' ', '\n'),
    value: val,
    fullMark: 10,
  }))
  return (
    <ResponsiveContainer width="100%" height={240}>
      <RadarChart cx="50%" cy="50%" outerRadius="72%" data={data}>
        <PolarGrid stroke="rgba(255,255,255,0.08)" />
        <PolarAngleAxis dataKey="subject" tick={{ fill: '#888', fontSize: 9 }} />
        <PolarRadiusAxis angle={30} domain={[0, 10]} tick={false} axisLine={false} />
        <Radar dataKey="value" stroke={color} fill={color} fillOpacity={0.3} />
        <Tooltip
          contentStyle={{ background: '#0d1117', borderColor: `${color}50`, borderRadius: 10 }}
          itemStyle={{ color: '#fff', fontSize: 11 }}
          formatter={v => [`${v}/10`]}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

// ── NEW: Metric Governance Panel — how traits govern each evaluation metric ──────
function TraitMetricGovernance({ traitToMetricWeights, metricTraitDescriptions, traitLabels }) {
  if (!traitToMetricWeights) return null
  const metrics = Object.keys(METRIC_LABELS)

  return (
    <>
      {metrics.map(metric => {
        const weights = traitToMetricWeights[metric] || {}
        const description = metricTraitDescriptions?.[metric] || ''
        const color = METRIC_COLORS[metric]
        const positiveTraits = Object.entries(weights).filter(([, w]) => w > 0).sort((a, b) => b[1] - a[1])
        const negativeTraits = Object.entries(weights).filter(([, w]) => w < 0)

        return (
          <div key={metric} className="rounded-xl border p-4 transition-all hover:scale-[1.01]"
               style={{ borderColor: `${color}30`, background: `${color}08` }}>
            <div className="flex items-start gap-3 mb-3">
              <span className="text-2xl">{METRIC_ICONS[metric]}</span>
              <div className="flex-1">
                <h4 className="font-black text-white text-sm">{METRIC_LABELS[metric]}</h4>
                <p className="text-[11px] text-[var(--text-muted)] mt-0.5 leading-relaxed">{description}</p>
              </div>
              <span className="text-[10px] px-2 py-1 rounded-full font-bold"
                    style={{ background: `${color}20`, color, border: `1px solid ${color}40` }}>
                {Object.keys(weights).length} traits
              </span>
            </div>

            {/* Positive weight bars */}
            <div className="space-y-1.5 mb-2">
              {positiveTraits.map(([trait, weight]) => {
                const barWidth = Math.round(weight * 100)
                return (
                  <div key={trait} className="flex items-center gap-2">
                    <span className="text-sm w-5">{TRAIT_ICONS[trait] || '•'}</span>
                    <span className="text-[11px] text-white w-36 flex-shrink-0">
                      {traitLabels?.[trait] || trait}
                    </span>
                    <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700"
                           style={{ width: `${barWidth}%`, background: color, boxShadow: `0 0 6px ${color}60` }} />
                    </div>
                    <span className="text-[11px] font-black w-10 text-right" style={{ color }}>
                      +{Math.round(weight * 100)}%
                    </span>
                  </div>
                )
              })}
              {negativeTraits.map(([trait, weight]) => (
                <div key={trait} className="flex items-center gap-2">
                  <span className="text-sm w-5">{TRAIT_ICONS[trait] || '•'}</span>
                  <span className="text-[11px] text-[var(--text-muted)] w-36 flex-shrink-0 line-through">
                    {traitLabels?.[trait] || trait}
                  </span>
                  <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-700"
                         style={{ width: `${Math.abs(weight) * 100}%`, background: '#f87171' }} />
                  </div>
                  <span className="text-[11px] font-black w-10 text-right text-red-400">
                    {Math.round(weight * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </>
  )
}

// ── NEW: Per-agent trait × metric influence heatmap ──────────────────────────
function InfluenceHeatmap({ traitMetricInfluence, traitLabels, color }) {
  if (!traitMetricInfluence || Object.keys(traitMetricInfluence).length === 0) return null
  const metrics = Object.keys(METRIC_LABELS).filter(m => traitMetricInfluence[m])

  // Collect all unique traits across all metrics
  const allTraits = [...new Set(metrics.flatMap(m => Object.keys(traitMetricInfluence[m] || {})))]

  const getCellColor = (score) => {
    if (score >= 8) return { bg: `${color}40`, text: color, glow: `0 0 8px ${color}60` }
    if (score >= 6) return { bg: `${color}20`, text: `${color}cc`, glow: 'none' }
    if (score >= 4) return { bg: 'rgba(255,255,255,0.05)', text: '#888', glow: 'none' }
    return { bg: 'rgba(255,0,0,0.08)', text: '#f87171', glow: 'none' }
  }

  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3 flex items-center gap-1">
        <span>🗂</span> Trait × Metric Influence (persona trait scores driving each metric)
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-[11px]">
          <thead>
            <tr>
              <th className="pb-2 pr-3 text-[var(--text-muted)] font-bold w-32">Trait \ Metric</th>
              {metrics.map(m => (
                <th key={m} className="pb-2 px-2 text-center font-bold" style={{ color: METRIC_COLORS[m] }}>
                  {METRIC_ICONS[m]} {METRIC_LABELS[m]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {allTraits.map(trait => (
              <tr key={trait}>
                <td className="py-1.5 pr-3 text-[var(--text-muted)] font-semibold">
                  {TRAIT_ICONS[trait] || ''} {traitLabels?.[trait] || trait}
                </td>
                {metrics.map(m => {
                  const score = traitMetricInfluence[m]?.[trait]
                  if (score === undefined) {
                    return <td key={m} className="py-1.5 px-2 text-center text-[var(--text-muted)]">—</td>
                  }
                  const c = getCellColor(score)
                  return (
                    <td key={m} className="py-1.5 px-2 text-center">
                      <span className="inline-block rounded-lg px-2 py-0.5 font-black"
                            style={{ background: c.bg, color: c.text, boxShadow: c.glow }}>
                        {score}/10
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-[var(--text-muted)] mt-2 italic">
        Cells show the agent's raw trait score (1-10). Higher = stronger influence on that evaluation metric.
        Red-tinted cells indicate this trait penalises the metric (e.g. high Speed hurts Faithfulness).
      </p>
    </div>
  )
}

// ── NEW: Trait-weighted expected vs actual comparison ───────────────────────
function TraitExpectedVsActual({ traitWeightedExpected, actual, color }) {
  const metrics = Object.keys(METRIC_LABELS)
  if (!traitWeightedExpected) return null
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3 flex items-center gap-1">
        <span>📐</span> Trait-Expected vs Actual Score
      </p>
      <div className="space-y-2">
        {metrics.map(m => {
          const expected = traitWeightedExpected[m] ?? 0
          const got      = actual?.[m] ?? 0
          const expPct   = Math.round(expected * 100)
          const gotPct   = pct(got)
          const diff     = gotPct - expPct
          return (
            <div key={m}>
              <div className="flex items-center justify-between text-[11px] mb-0.5">
                <span className="text-[var(--text-muted)] flex items-center gap-1">
                  {METRIC_ICONS[m]} {METRIC_LABELS[m]}
                </span>
                <span className={diff > 2 ? 'text-emerald-400 font-bold' : diff < -2 ? 'text-red-400 font-bold' : 'text-[var(--text-muted)]'}>
                  {diff > 0 ? '+' : ''}{diff}pp vs persona expectation
                </span>
              </div>
              <div className="relative h-3 rounded-full bg-white/5 overflow-hidden">
                {/* Trait-expected bar (ghost) */}
                <div className="absolute h-full rounded-full"
                     style={{ width: `${expPct}%`, background: 'rgba(255,255,255,0.12)' }} />
                {/* Actual bar */}
                <div className="absolute h-full rounded-full transition-all duration-700"
                     style={{
                       width: `${gotPct}%`,
                       background: diff >= 0 ? color : '#f87171',
                       boxShadow: diff >= 0 ? `0 0 6px ${color}80` : '0 0 6px #f8717180',
                       opacity: 0.85,
                     }} />
              </div>
              <div className="flex justify-between text-[10px] text-[var(--text-muted)] mt-0.5">
                <span>Trait-expected: {expPct}%</span>
                <span>Actual: {gotPct}%</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ── 2. Separated trait comparison charts ────────────────────────
function TraitSeparatedCharts({ agents, traitLabels }) {
  if (!traitLabels) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
      {Object.entries(traitLabels).map(([traitKey, traitLabel]) => {
        const data = AGENT_KEYS.map(k => ({
          agent: AGENT_META[k].short,
          fullAgent: AGENT_META[k].label,
          score: agents[k]?.trait_scores?.[traitKey] ?? 0,
          fill: AGENT_META[k].color
        }))

        return (
          <div key={traitKey} className="rounded-xl border border-white/5 bg-white/[0.02] p-4 hover:bg-white/[0.04] transition-colors">
            <h4 className="text-sm font-bold text-center mb-4 text-white tracking-wide">{traitLabel}</h4>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data} margin={{ top:5, right:5, left:-20, bottom:25 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="agent" tick={{ fill:'var(--text-muted)', fontSize:10 }} angle={-35} textAnchor="end" interval={0} />
                <YAxis domain={[0,10]} tick={{ fill:'var(--text-muted)', fontSize:10 }} />
                <Tooltip cursor={{ fill:'rgba(255,255,255,0.04)' }}
                         content={<MetricTooltip data={data} metricLabel={traitLabel} unit="/10" />} />
                <Bar dataKey="score" radius={[3,3,0,0]} maxBarSize={35}>
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      })}
    </div>
  )
}

// ── 3. Trait winner table ────────────────────────────────────────────────────
function TraitComparisonTable({ traitComparison, traitDimensions }) {
  if (!traitComparison || !traitDimensions) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] bg-white/5">
            <th className="px-4 py-3 font-bold">Trait Dimension</th>
            <th className="px-4 py-3 font-bold text-emerald-300">🥇 Winner</th>
            <th className="px-4 py-3 font-bold text-blue-300">🥈 Runner-Up</th>
            <th className="px-4 py-3 font-bold text-red-300">⚠ Weakest</th>
            <th className="px-4 py-3 font-bold">All Scores /10</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {traitDimensions.map(dim => {
            const row = traitComparison[dim]
            if (!row) return null
            const winnerMeta = AGENT_META[row.winner_key]
            const runnerMeta = AGENT_META[row.runner_up_key]
            const weakMeta   = AGENT_META[row.weakest_key]
            return (
              <tr key={dim} className="hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-3">
                  <span className="text-sm font-bold text-white">{row.label}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span>{winnerMeta?.emoji}</span>
                    <div>
                      <p className="text-xs font-bold text-emerald-300">{winnerMeta?.label}</p>
                      <p className="text-[11px] text-[var(--text-muted)]">{row.winner_score}/10</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span>{runnerMeta?.emoji}</span>
                    <div>
                      <p className="text-xs font-semibold text-blue-200">{runnerMeta?.label}</p>
                      <p className="text-[11px] text-[var(--text-muted)]">{row.runner_up_score}/10</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span>{weakMeta?.emoji}</span>
                    <div>
                      <p className="text-xs font-semibold text-red-300">{weakMeta?.label}</p>
                      <p className="text-[11px] text-[var(--text-muted)]">{row.weakest_score}/10</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {AGENT_KEYS.map(k => {
                      const s = row.all_scores?.[k] ?? 0
                      const meta = AGENT_META[k]
                      return (
                        <div key={k} className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold"
                             style={{ background: `${meta.color}18`, border: `1px solid ${meta.color}30`, color: meta.color }}>
                          {meta.short}: {s}
                        </div>
                      )
                    })}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── 4. Baseline vs Actual RAG metric bars ─────────────────────────────────────
function BaselineVsActual({ baseline, actual }) {
  const metrics = ['faithfulness_score','reasoning_score','agreement_score','coverage_score','reliability_score']
  return (
    <div className="space-y-2">
      {metrics.map(m => {
        const b = pct(baseline?.[m] ?? 0)
        const a = pct(actual?.[m] ?? 0)
        const diff = a - b
        return (
          <div key={m} className="space-y-1">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-[var(--text-muted)]">{METRIC_LABELS[m]}</span>
              <span className={diff > 0 ? 'text-emerald-400' : diff < 0 ? 'text-red-400' : 'text-[var(--text-muted)]'}>
                {diff > 0 ? '+' : ''}{diff}pp
              </span>
            </div>
            <div className="relative h-2 rounded-full bg-white/5 overflow-hidden">
              <div className="absolute h-full rounded-full bg-white/15" style={{ width: `${b}%` }} />
              <div className="absolute h-full rounded-full" style={{ width: `${a}%`, background: diff >= 0 ? '#39ff1480' : '#f472b680' }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── 5. Per-question reliability trend ─────────────────────────────────────────
function AgentTrendChart({ perQuestion, color }) {
  const data = (perQuestion || []).map((q, i) => ({
    q: `Q${i+1}`, reliability: pct(q.scores?.reliability_score ?? 0),
    faithfulness: pct(q.scores?.faithfulness_score ?? 0),
  }))
  if (!data.length) return <p className="text-xs text-center py-6 text-[var(--text-muted)]">No question data yet</p>
  return (
    <ResponsiveContainer width="100%" height={130}>
      <LineChart data={data} margin={{ top:4, right:10, left:-20, bottom:0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
        <XAxis dataKey="q" tick={{ fill: '#666', fontSize: 10 }} />
        <YAxis domain={[0,100]} tick={{ fill: '#666', fontSize: 10 }} unit="%" />
        <Tooltip contentStyle={{ background:'#0d1117', borderColor:`${color}40`, borderRadius:10 }}
                 itemStyle={{ color:'#fff', fontSize:11 }} formatter={v => [`${v}%`]} />
        <Line type="monotone" dataKey="reliability" stroke={color} dot={{ r:3 }} strokeWidth={2} name="Reliability" />
        <Line type="monotone" dataKey="faithfulness" stroke={`${color}80`} dot={false} strokeWidth={1.5} strokeDasharray="4 2" name="Faithfulness" />
      </LineChart>
    </ResponsiveContainer>
  )
}

function MetricTooltip({ active, payload, data, metricLabel }) {
  if (!active || !data) return null;
  return (
    <div className="p-3 rounded-xl border shadow-xl" style={{ background: '#0d1117', borderColor: 'rgba(91,127,255,0.3)' }}>
      <p className="text-xs font-bold text-[var(--text-muted)] mb-3 uppercase tracking-wider">{metricLabel}</p>
      <div className="space-y-1.5">
        {data.map((entry, idx) => {
          const isHovered = payload && payload[0] && payload[0].payload.agent === entry.agent;
          return (
            <div key={idx} className={`flex items-center justify-between gap-6 transition-opacity ${isHovered ? 'opacity-100' : 'opacity-50'}`}>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: entry.fill, boxShadow: isHovered ? `0 0 6px ${entry.fill}` : 'none' }} />
                <span className={`text-[11px] ${isHovered ? 'text-white font-bold' : 'text-gray-400'}`}>{entry.fullAgent}</span>
              </div>
              <span className={`text-[11px] ${isHovered ? 'text-white font-bold' : 'text-gray-400'}`}>{entry.score}%</span>
            </div>
          )
        })}
      </div>
    </div>
  );
}

// ── 6. Separated metric charts (RAG) ─────────────────────────────────────────────
function MetricSeparatedCharts({ agents }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
      {Object.entries(METRIC_LABELS).map(([metricKey, metricLabel]) => {
        const data = AGENT_KEYS.map(k => ({
          agent: AGENT_META[k].short,
          fullAgent: AGENT_META[k].label,
          score: pct(agents[k]?.actual_scores?.[metricKey] ?? 0),
          fill: AGENT_META[k].color
        }))

        return (
          <div key={metricKey} className="rounded-xl border border-white/5 bg-white/[0.02] p-4 hover:bg-white/[0.04] transition-colors">
            <h4 className="text-sm font-bold text-center mb-4 text-white tracking-wide">{metricLabel}</h4>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data} margin={{ top:5, right:5, left:-20, bottom:25 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="agent" tick={{ fill:'var(--text-muted)', fontSize:10 }} angle={-35} textAnchor="end" interval={0} />
                <YAxis domain={[0,100]} tick={{ fill:'var(--text-muted)', fontSize:10 }} unit="%" />
                <Tooltip cursor={{ fill:'rgba(255,255,255,0.04)' }}
                         content={<MetricTooltip data={data} metricLabel={metricLabel} />} />
                <Bar dataKey="score" radius={[3,3,0,0]} maxBarSize={35}>
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      })}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AgentPerformanceReport() {
  const [report, setReport]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const fetch = async () => {
    setLoading(true); setError(null)
    try { setReport(await getAgentReport(200)) }
    catch (e) { setError(e?.response?.data?.detail || e.message || 'Failed') }
    finally { setLoading(false) }
  }
  useEffect(() => { fetch() }, [])

  const agents                  = report?.agents                   || {}
  const traitComparison         = report?.trait_comparison          || {}
  const traitDimensions         = report?.trait_dimensions          || []
  const traitLabels             = report?.trait_labels              || {}
  const traitToMetricWeights    = report?.trait_to_metric_weights   || {}
  const metricTraitDescriptions = report?.metric_trait_descriptions || {}
  const totalRecords            = report?.total_records             || 0
  const questions               = report?.questions_analysed        || []

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-black flex items-center gap-2"
              style={{ background:'linear-gradient(135deg,#5b7fff,#f472b6)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent', backgroundClip:'text' }}>
            <BarChart2 size={22} style={{ color:'#5b7fff', WebkitTextFillColor:'unset' }} />
            Agent Performance Report
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            <strong className="text-white">{totalRecords}</strong> stored records ·{' '}
            <strong className="text-white">{questions.length}</strong> unique questions · Trait scores are grounded in each agent's defined persona
          </p>
        </div>
        <button onClick={fetch} disabled={loading}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold disabled:opacity-50"
                style={{ background:'rgba(91,127,255,0.15)', border:'1px solid rgba(91,127,255,0.35)', color:'#7c9fff' }}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{error}</div>}
      {loading && !report && (
        <div className="flex items-center justify-center py-20 text-[var(--text-muted)]">
          <RefreshCw size={28} className="animate-spin mr-3" /> Loading…
        </div>
      )}

      {report && (<>

        {/* ── Section 1: Cross-agent trait comparison bar chart ── */}
        <div className="glass-card p-6" style={{ borderColor:'rgba(191,95,255,0.25)' }}>
          <h3 className="text-sm font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-1 flex items-center gap-2">
            <Zap size={14} style={{ color:'#bf5fff' }} /> Persona Trait Comparison — All 6 Agents (Score /10)
          </h3>
          <p className="text-xs text-[var(--text-muted)] mb-5">
            Each trait is scored 1–10 based on the agent's backstory, role, and reasoning style. Higher = stronger on that dimension.
          </p>
          <TraitSeparatedCharts agents={agents} traitLabels={traitLabels} />
        </div>

        {/* ── Section 2: Trait winner table ── */}
        <div className="glass-card overflow-hidden" style={{ borderColor:'rgba(0,245,255,0.2)' }}>
          <div className="p-5 border-b border-white/5 flex items-center gap-2"
               style={{ background:'linear-gradient(135deg,rgba(0,245,255,0.06),rgba(91,127,255,0.04))' }}>
            <Trophy size={18} style={{ color:'#ffd700' }} />
            <div>
              <h3 className="text-base font-black text-white">Trait-by-Trait Winner Analysis</h3>
              <p className="text-xs text-[var(--text-muted)]">Which agent wins, who's second, and who needs the most improvement — per dimension</p>
            </div>
          </div>
          <TraitComparisonTable traitComparison={traitComparison} traitDimensions={traitDimensions} />
        </div>

        {/* ── Section 3: RAG metric grouped bar ── */}
        <div className="glass-card p-6" style={{ borderColor:'rgba(91,127,255,0.25)' }}>
          <h3 className="text-sm font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-5 flex items-center gap-2">
            <Activity size={15} /> RAG Metric Comparison — Averaged Across All Queries (%)
          </h3>
          <MetricSeparatedCharts agents={agents} />
        </div>

        {/* ── Section 4: Per-agent scorecards ── */}
        <h3 className="text-sm font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] flex items-center gap-2">
          <Shield size={15} /> Per-Agent Scorecard — Trait Radar, Scores & Verdict
        </h3>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          {AGENT_KEYS.map(key => {
            const a = agents[key]; if (!a) return null
            const meta = AGENT_META[key]
            const v    = a.verdict || {}
            return (
              <div key={key} className="glass-card p-6 space-y-5 relative overflow-hidden"
                   style={{ borderColor:`${meta.color}30` }}>
                <div className="absolute inset-0 pointer-events-none opacity-25"
                     style={{ background:`radial-gradient(circle at top right, ${meta.color}18 0%, transparent 60%)` }} />

                {/* Header */}
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-xl flex items-center justify-center text-2xl flex-shrink-0"
                         style={{ background:`${meta.color}18`, border:`1px solid ${meta.color}35` }}>
                      {meta.emoji}
                    </div>
                    <div>
                      <h4 className="font-black text-white text-base">{meta.label}</h4>
                      <p className="text-xs text-[var(--text-muted)] mt-0.5">{a.role}</p>
                      <p className="text-[11px] mt-0.5" style={{ color:meta.color }}>
                        {a.total_questions} question{a.total_questions !== 1 ? 's' : ''} evaluated
                      </p>
                    </div>
                  </div>
                  <VerdictBadge verdict={v.overall_verdict} />
                </div>

                {/* Qualitative trait tags */}
                <div className="flex flex-wrap gap-1.5">
                  {(a.traits || []).map(t => (
                    <span key={t} className="text-[11px] rounded-full px-2.5 py-0.5 font-semibold"
                          style={{ background:`${meta.color}15`, border:`1px solid ${meta.color}30`, color:meta.color }}>
                      {t}
                    </span>
                  ))}
                </div>

                {/* Dominant traits highlight */}
                {(a.dominant_traits || []).length > 0 && (
                  <div className="rounded-xl border p-3 space-y-1.5"
                       style={{ borderColor:`${meta.color}25`, background:`${meta.color}08` }}>
                    <p className="text-[10px] uppercase tracking-[0.2em] font-bold mb-2"
                       style={{ color:meta.color }}>
                      ★ Dominant Defining Traits
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {(a.dominant_traits || []).map(t => (
                        <span key={t} className="text-xs font-black px-3 py-1 rounded-full"
                              style={{ background:meta.color, color:'#000' }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Persona trait scores — 0.0–1.0 per trait (original + inferred) */}
                {Object.keys(a.persona_trait_scores || {}).length > 0 && (
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3 flex items-center gap-1">
                      <Brain size={11} /> Persona Trait Encoding (0.0 – 1.0)
                    </p>
                    <div className="space-y-1.5">
                      {Object.entries(a.persona_trait_scores).map(([trait, score]) => {
                        const isDominant = (a.dominant_traits || []).includes(trait)
                        const barWidth = Math.round(score * 100)
                        return (
                          <div key={trait} className="flex items-center gap-3">
                            <span className={`text-[11px] w-40 flex-shrink-0 ${isDominant ? 'font-bold' : 'text-[var(--text-muted)]'}`}
                                  style={isDominant ? { color:meta.color } : {}}>
                              {trait}{isDominant ? ' ★' : ''}
                            </span>
                            <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                              <div className="h-full rounded-full transition-all duration-700"
                                   style={{
                                     width:`${barWidth}%`,
                                     background: isDominant ? meta.color : `${meta.color}70`,
                                     boxShadow: isDominant ? `0 0 6px ${meta.color}80` : 'none',
                                   }} />
                            </div>
                            <span className="text-[11px] font-bold w-9 text-right"
                                  style={{ color: isDominant ? meta.color : '#666' }}>
                              {score.toFixed(2)}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                    {a.normalization_note && (
                      <p className="text-[10px] text-[var(--text-muted)] mt-3 leading-relaxed italic border-t border-white/5 pt-2">
                        {a.normalization_note}
                      </p>
                    )}
                  </div>
                )}

                {/* Trait score bars (1-10 dimensions) */}
                <div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3 flex items-center gap-1">
                    <Target size={11} /> Dimension Scores (1 – 10)
                  </p>
                  <div className="space-y-2">
                    {Object.entries(a.trait_scores || {}).map(([dim, score]) => (
                      <div key={dim} className="flex items-center gap-3">
                        <span className="text-[11px] text-[var(--text-muted)] w-36 flex-shrink-0">
                          {traitLabels[dim] || dim}
                        </span>
                        <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                          <div className="h-full rounded-full transition-all duration-700"
                               style={{ width:`${score * 10}%`, background:meta.color, boxShadow:`0 0 6px ${meta.color}60` }} />
                        </div>
                        <span className="text-xs font-black w-8 text-right" style={{ color:meta.color }}>{score}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Trait radar */}
                <div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-1">Trait Profile Radar</p>
                  <TraitRadar traitScores={a.trait_scores} traitLabels={traitLabels} color={meta.color} />
                </div>

                {/* ── Trait × Metric Influence Heatmap ── */}
                <InfluenceHeatmap
                  traitMetricInfluence={a.trait_metric_influence}
                  traitLabels={traitLabels}
                  color={meta.color}
                />

                {/* ── Trait-Expected vs Actual ── */}
                <TraitExpectedVsActual
                  traitWeightedExpected={a.trait_weighted_expected}
                  actual={a.actual_scores}
                  color={meta.color}
                />

                {/* Baseline vs Actual RAG metrics */}
                <div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3 flex items-center gap-1">
                    <Zap size={11} /> Baseline vs Actual (RAG metrics)
                  </p>
                  <BaselineVsActual baseline={a.baseline_scores} actual={a.actual_scores} />
                </div>

                {/* Trend across questions */}
                <div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-2 flex items-center gap-1">
                    <TrendingUp size={11} /> Reliability across questions
                  </p>
                  <AgentTrendChart perQuestion={a.per_question || []} color={meta.color} />
                </div>

                {/* Verdict boxes */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/8 p-3">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-emerald-300 mb-1 flex items-center gap-1">
                      <Star size={10} /> Best at
                    </p>
                    <p className="text-sm font-bold text-white">{v.best_at || '—'}</p>
                  </div>
                  <div className="rounded-xl border border-red-500/25 bg-red-500/8 p-3">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-red-300 mb-1 flex items-center gap-1">
                      <TrendingDown size={10} /> Needs work on
                    </p>
                    <p className="text-sm font-bold text-white">{v.worst_at || '—'}</p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* ── Section 5: Leaderboard ── */}
        <div className="glass-card p-6" style={{ borderColor:'rgba(0,245,255,0.2)' }}>
          <h3 className="text-sm font-bold uppercase tracking-[0.2em] mb-5 flex items-center gap-2" style={{ color:'#67e8f9' }}>
            <Award size={15} /> Overall Reliability Leaderboard
          </h3>
          <div className="space-y-3">
            {AGENT_KEYS
              .map(k => ({ key:k, score:pct(agents[k]?.actual_scores?.reliability_score ?? 0), meta:AGENT_META[k] }))
              .sort((a,b) => b.score - a.score)
              .map((item, rank) => (
                <div key={item.key} className="flex items-center gap-4 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
                  <span className="text-lg font-black w-6 text-center"
                        style={{ color: rank===0?'#ffd700': rank===1?'#c0c0c0': rank===2?'#cd7f32':'#555' }}>
                    {rank+1}
                  </span>
                  <span className="text-xl">{item.meta.emoji}</span>
                  <div className="flex-1">
                    <p className="text-sm font-bold text-white">{item.meta.label}</p>
                    <p className="text-[11px] text-[var(--text-muted)]">{agents[item.key]?.role || ''}</p>
                  </div>
                  <div className="w-36 h-2 rounded-full bg-white/5 overflow-hidden">
                    <div className="h-full rounded-full" style={{ width:`${item.score}%`, background:item.meta.color, boxShadow:`0 0 8px ${item.meta.color}80` }} />
                  </div>
                  <span className="text-sm font-black w-12 text-right" style={{ color:item.meta.color }}>{item.score}%</span>
                </div>
              ))}
          </div>
        </div>

        {/* ── Section 6: Metric Governance Panel ── */}
        <div className="glass-card p-6" style={{ borderColor:'rgba(191,95,255,0.2)' }}>
          <div className="mb-5">
            <h3 className="text-sm font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] flex items-center gap-2 mb-1">
              <Brain size={15} style={{ color:'#bf5fff' }} /> Evaluation Metric Governance — Persona Trait Influence
            </h3>
            <p className="text-xs text-[var(--text-muted)]">
              Each evaluation metric is <strong className="text-white">governed by specific persona trait dimensions</strong>.
              The weights below show which traits drive which metric, and why certain agents score differently by design.
              Negative weights indicate traits that <strong className="text-red-400">penalise</strong> a metric (e.g. high Speed hurts Faithfulness).
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            <TraitMetricGovernance
              traitToMetricWeights={traitToMetricWeights}
              metricTraitDescriptions={metricTraitDescriptions}
              traitLabels={traitLabels}
            />
          </div>
        </div>

      </>)}
    </div>
  )
}
