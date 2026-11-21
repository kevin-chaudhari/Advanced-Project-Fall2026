import { Fragment, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, Flag } from 'lucide-react'
import { cx } from '../ui'
import { ReviewDecision } from '../primitives'

/*
 * Experiment Lab result views. Everything here is computed by the backend from real runs
 * (GET /experiments/{id}); these components only lay it out.
 */

// warm categorical palette that sits on the cream theme; answers keep their colour across views
const ANSWER_COLORS = ['#6E5A3E', '#5C726F', '#A9773A', '#8E463D', '#66745A', '#3B3731', '#B79A6E', '#475957', '#C18D4D', '#7D6F8A']

export function useAnswerColors(analysis) {
  return useMemo(() => {
    const order = []
    const push = (a) => { if (a && !order.includes(a)) order.push(a) }
    push(analysis?.baseline?.answer)
    Object.entries(analysis?.answer_counts || {}).sort((a, b) => b[1] - a[1]).forEach(([a]) => push(a))
    const map = Object.fromEntries(order.map((a, i) => [a, ANSWER_COLORS[i % ANSWER_COLORS.length]]))
    return (a) => map[a] || '#8A8170'
  }, [analysis])
}

export function AnswerChip({ answer, color, className }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 text-[12px] font-medium text-ink', className)}>
      <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} aria-hidden />
      <span className="truncate">{answer || '—'}</span>
    </span>
  )
}

const fmtVal = (v) => (typeof v === 'number' ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }) : String(v))
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)

/** One row per factor: every tried value in order, coloured by the answer it produced. */
export function FactorSweeps({ factors, colorOf, onOpenRun }) {
  if (!factors?.length) return <p className="text-[13px] text-muted">No varied runs have finished yet.</p>
  return (
    <div className="grid gap-x-6 gap-y-4 xl:grid-cols-2">
      {factors.map((f) => (
        <div key={f.factor} className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="text-[13.5px] font-semibold text-ink capitalize">{f.label}{f.unit ? <span className="font-normal text-muted"> ({f.unit.replace(/^\((.*)\)$/, '$1')})</span> : null}</h3>
            <span className="text-[12px] text-muted">
              {f.answer_flips ? <b className="text-ink">{f.answer_flips} of {f.run_count} changed the answer</b> : 'answer never changed'}
              {f.review_flips ? `, ${f.review_flips} changed the review decision` : ''}
              {f.confidence_range && `, confidence ${pct(f.confidence_range[0])}–${pct(f.confidence_range[1])}`}
            </span>
          </div>
          <div className="mt-2 flex items-stretch overflow-x-auto pb-1">
            {f.points.map((p, i) => {
              const prev = f.points[i - 1]
              const flip = prev && f.numeric && prev.answer !== p.answer
              return (
                <Fragment key={`${p.run_index}-${i}`}>
                  {flip && <div className="mx-1 w-px shrink-0 bg-ink/60" title={`Answer changes between ${fmtVal(prev.value)} and ${fmtVal(p.value)}`} />}
                  <button type="button" onClick={() => onOpenRun?.(p.run_index)}
                    className={cx('group min-w-[84px] shrink-0 rounded-md border px-2 py-1 text-left focus-ring mr-1',
                      p.is_baseline ? 'border-ink/70 bg-surface' : 'border-line bg-surface hover:bg-well')}
                    title={`${p.answer} — confidence ${pct(p.confidence)} — ${p.review_decision}`}>
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-[12.5px] font-semibold tabular-nums text-ink">{fmtVal(p.value)}</span>
                      {p.is_baseline && <span className="text-[10px] font-medium uppercase tracking-wide text-muted">base</span>}
                    </div>
                    <div className="mt-1 h-1.5 rounded-full" style={{ background: colorOf(p.answer) }} />
                    <div className="mt-1 truncate text-[11px] text-muted">{p.answer}</div>
                    <div className="mt-0.5 flex items-center justify-between text-[10.5px] tabular-nums text-muted">
                      <span>{pct(p.confidence)}</span>
                      <span>{p.review_decision === 'AUTO_RESOLVE' ? 'auto' : 'review'}</span>
                    </div>
                  </button>
                </Fragment>
              )
            })}
          </div>
          {f.transitions?.length > 0 && (
            <ul className="mt-1.5 space-y-0.5 text-[12px] text-muted">
              {f.transitions.map((t, i) => (
                <li key={i}>Between <b className="text-ink tabular-nums">{fmtVal(t.from_value)}</b> and <b className="text-ink tabular-nums">{fmtVal(t.to_value)}</b>: {t.from_answer} → <b className="text-ink">{t.to_answer}</b></li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

const AGENT_SHORT = { diagnostic_expert: 'Diagnostic expert', pattern_agent: 'Pattern recognition', aggressive_agent: 'Rapid triage',
  verification: 'Verification', ambiguity: 'Ambiguity', human_review_coordinator: 'Final coordinator' }
const STAGE_NAME = {
  query_prep: 'Reading the question', initial_rag: 'Evidence retrieval', numerical_analysis: 'Hypothesis scoring',
  phase1: 'First opinion', collaboration: 'Agents discuss', verification: 'Verification', evidence_check: 'Evidence check',
  targeted_rag: 'Extra evidence search', targeted_rerun: 'Agent re-checks', ambiguity: 'Ambiguity check', council: 'Council',
  final_coordinator: 'Final answer', claim_validation: 'Claim check', review_gate: 'Review gate',
}
const VERB = { analyze: '', deliberate: 'speaks' }
export const stepName = (s) => {
  const [stage, agent, verb] = s.key.split('#')[0].split(':')
  const n = Number(s.key.split('#')[1])
  const who = agent ? AGENT_SHORT[agent] || agent.replace(/_/g, ' ') : ''
  const base = STAGE_NAME[stage] || stage.replace(/_/g, ' ')
  const label = [base, who, verb && VERB[verb] !== undefined ? VERB[verb] : verb].filter(Boolean).join(' · ')
  return n > 1 ? `${label} (round ${n})` : label
}

/** Which pipeline steps made a different decision across runs, aligned by step identity. */
export function StepDivergence({ steps, firstKey, colorOf, total }) {
  const [open, setOpen] = useState(firstKey)
  const [onlyChanged, setOnlyChanged] = useState(true)
  const signal = (s) => s.changed_runs > 0 && s.missing_runs < total / 2
  const shown = onlyChanged ? steps.filter(signal) : steps
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm bg-warning-500" />linked to the final answer</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm bg-slate-300" />changed, not linked</span>
        <label className="ml-auto inline-flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} className="accent-primary-700" />
          Only steps that changed in most runs ({steps.filter(signal).length} of {steps.length})
        </label>
      </div>
      <ol className="divide-y divide-line rounded-lg border border-line bg-surface">
        {shown.map((s) => {
          const frac = s.run_count ? s.changed_runs / total : 0
          const isOpen = open === s.key
          return (
            <li key={s.key}>
              <button type="button" onClick={() => setOpen(isOpen ? null : s.key)} aria-expanded={isOpen}
                className="grid w-full grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2 text-left hover:bg-well focus-ring sm:grid-cols-[16px_minmax(0,220px)_minmax(0,1fr)_auto]">
                <ChevronRight size={14} className={cx('text-muted transition-transform', isOpen && 'rotate-90')} />
                <span className="truncate text-[12.5px] font-medium text-ink">
                  {s.key === firstKey && <Flag size={12} className="mr-1 inline text-danger-600" aria-label="First step that diverges with the answer" />}
                  {stepName(s)}
                </span>
                <span className="hidden sm:block h-2 rounded-full bg-well">
                  <span className={cx('block h-full rounded-full', s.answer_linked ? 'bg-warning-500' : 'bg-slate-300')} style={{ width: `${Math.max(frac * 100, s.changed_runs ? 3 : 0)}%` }} />
                </span>
                <span className="text-[11.5px] tabular-nums text-muted whitespace-nowrap">
                  {s.changed_runs}/{total} changed{s.missing_runs ? `, absent in ${s.missing_runs}` : ''}
                </span>
              </button>
              {isOpen && (
                <div className="px-3 pb-3 pl-10">
                  <p className="text-[12px] text-muted">Baseline decision: <span className="text-ink">{s.baseline_signature}</span>
                    {s.answer_linked && <> — runs that took the same path here mostly reached the same answer ({pct(s.answer_link_score)}).</>}
                    {s.missing_runs > 0 && <> This step did not happen at all in {s.missing_runs} run(s).</>}</p>
                  <table className="mt-2 w-full text-[12px]">
                    <thead><tr className="text-left text-muted"><th className="py-1 pr-3 font-medium">Decision at this step</th><th className="py-1 pr-3 font-medium">Runs</th><th className="py-1 font-medium">Final answers</th></tr></thead>
                    <tbody>
                      {s.variants.map((v) => (
                        <tr key={v.signature} className="border-t border-line align-top">
                          <td className="py-1.5 pr-3 text-ink">{v.signature}</td>
                          <td className="py-1.5 pr-3 tabular-nums">{v.count}</td>
                          <td className="py-1.5"><div className="flex flex-wrap gap-x-3 gap-y-0.5">{Object.entries(v.answers).map(([a, n]) => <span key={a} className="tabular-nums"><AnswerChip answer={`${a} ×${n}`} color={colorOf(a)} /></span>)}</div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/** Step ribbons: one row per representative run, one cell per aligned step; dark cells differ from the baseline. */
export function StepRibbons({ runs, divergence, colorOf }) {
  const [hover, setHover] = useState(null)
  const keys = divergence.map((d) => d.key)
  const base = runs[0]
  const baseSig = Object.fromEntries((base?.steps || []).map((s) => [s.key, s.signature]))
  return (
    <div>
      <div className="space-y-2">
        {runs.map((r) => {
          const sig = Object.fromEntries(r.steps.map((s) => [s.key, s]))
          return (
            <div key={r.run_index} className="grid grid-cols-1 gap-1 sm:grid-cols-[200px_minmax(0,1fr)] sm:items-center sm:gap-3">
              <div className="min-w-0">
                <p className="truncate text-[12.5px] font-medium text-ink">{r.label}</p>
                <AnswerChip answer={`${r.answer} · ${pct(r.confidence)}`} color={colorOf(r.answer)} className="text-muted" />
              </div>
              <div className="flex gap-px overflow-x-auto">
                {keys.map((k) => {
                  const s = sig[k]
                  const diff = s && base && r !== base && baseSig[k] !== undefined && s.signature !== baseSig[k]
                  const extra = s && baseSig[k] === undefined && r !== base
                  return (
                    <span key={k} onMouseEnter={() => setHover({ k, s, r })} onMouseLeave={() => setHover(null)}
                      className={cx('h-6 min-w-[8px] flex-1 rounded-[2px]', !s ? 'bg-transparent border border-dashed border-line' : diff ? 'bg-ink' : extra ? 'bg-warning-500' : 'bg-primary-200')}
                      title={s ? `${stepName({ key: k })}: ${s.signature}` : `${stepName({ key: k })}: did not run`} />
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-[2px] bg-primary-200" />same decision as baseline</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-[2px] bg-ink" />different decision</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-[2px] bg-warning-500" />step the baseline never ran</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-[2px] border border-dashed border-line" />step skipped</span>
      </div>
      <p className="mt-2 min-h-[20px] text-[12px] text-ink" aria-live="polite">
        {hover ? <><b>{stepName({ key: hover.k })}</b> in “{hover.r.label}”: {hover.s ? hover.s.signature : 'did not run'}</> : <span className="text-muted">Hover a cell to see the decision made at that step.</span>}
      </p>
    </div>
  )
}

/** All runs, with links to their traces and a two-run picker for the aligned compare. */
export function RunsTable({ runs, colorOf, selected, onToggle, highlight }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-[12.5px]">
        <thead className="bg-well text-left text-muted">
          <tr>
            <th className="w-8 px-3 py-2"><span className="sr-only">Compare</span></th>
            <th className="px-3 py-2 font-medium">Run</th>
            <th className="px-3 py-2 font-medium">Answer</th>
            <th className="px-3 py-2 font-medium">Confidence</th>
            <th className="px-3 py-2 font-medium">Review</th>
            <th className="px-3 py-2 font-medium">Trace</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_index} id={`run-${r.run_index}`} className={cx('border-t border-line', highlight === r.run_index && 'bg-primary-50')}>
              <td className="px-3 py-1.5">
                <input type="checkbox" aria-label={`Select ${r.label} for comparison`} disabled={r.status !== 'done'}
                  checked={selected.includes(r.run_index)} onChange={() => onToggle(r.run_index)} className="accent-primary-700" />
              </td>
              <td className="px-3 py-1.5 text-ink">
                {r.label}{r.is_baseline && <span className="ml-1.5 text-[10.5px] uppercase tracking-wide text-muted">baseline</span>}
                {r.status !== 'done' && <span className={cx('ml-2 text-[11px]', r.status === 'failed' ? 'text-danger-700' : 'text-muted')}>{r.status}{r.error ? `: ${r.error}` : ''}</span>}
              </td>
              <td className="px-3 py-1.5">{r.answer ? <AnswerChip answer={r.answer} color={colorOf(r.answer)} /> : '—'}</td>
              <td className="px-3 py-1.5 tabular-nums">{pct(r.confidence)}</td>
              <td className="px-3 py-1.5">{r.review_decision ? <ReviewDecision decision={r.review_decision} variant="inline" /> : '—'}</td>
              <td className="px-3 py-1.5">{r.trace_id ? <Link to={`/traces/${r.trace_id}`} className="font-medium text-primary-700 underline underline-offset-2">Open</Link> : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const STATE_STYLE = {
  same: 'border-line', different: 'border-warning-500 bg-warning-50/60', only_a: 'border-dashed border-line', only_b: 'border-dashed border-line',
}
const agentName = (k, fallback) => AGENT_SHORT[k] || fallback || k

/** Agent × run matrix for the whole experiment: each agent's finding per run; outlined cells moved away from the baseline. */
export function AgentMatrix({ agents, runs, colorOf, onPick }) {
  const [hover, setHover] = useState(null)
  if (!agents?.length) return <p className="text-[13px] text-muted">No agent data recorded for these runs.</p>
  const label = Object.fromEntries(runs.map((r) => [r.run_index, r.label]))
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="text-[12px]">
          <thead>
            <tr className="text-left text-muted">
              <th className="sticky left-0 bg-canvas py-1 pr-3 font-medium">Agent</th>
              <th className="py-1 pr-3 font-medium whitespace-nowrap">Changed</th>
              {agents[0].cells.map((c) => (
                <th key={c.run_index} className="px-px pb-1 align-bottom font-normal" title={label[c.run_index]}>
                  <span className="mx-auto block max-h-[86px] w-6 overflow-hidden whitespace-nowrap text-[10.5px] leading-6 [writing-mode:vertical-rl] rotate-180">{c.short || c.run_index}</span>
                </th>))}
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.agent}>
                <td className="sticky left-0 bg-canvas py-0.5 pr-3 font-medium text-ink whitespace-nowrap">{agentName(a.agent, a.name)}</td>
                <td className="py-0.5 pr-3 tabular-nums text-muted whitespace-nowrap">{a.changed_runs}/{a.cells.length - 1}</td>
                {a.cells.map((c) => (
                  <td key={c.run_index} className="px-px py-0.5">
                    <button type="button" onClick={() => onPick?.(c.run_index)} onMouseEnter={() => setHover({ a, c })} onMouseLeave={() => setHover(null)}
                      aria-label={`${agentName(a.agent)} in ${label[c.run_index]}: ${c.finding}`}
                      className={cx('block h-6 w-6 rounded-[3px] focus-ring', c.changed && 'ring-2 ring-ink ring-offset-1 ring-offset-canvas')}
                      style={{ background: c.finding ? colorOf(c.finding) : 'transparent', opacity: c.finding ? 1 : 0.3 }} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 min-h-[20px] text-[12px] text-ink" aria-live="polite">
        {hover ? <><b>{agentName(hover.a.agent, hover.a.name)}</b> in “{label[hover.c.run_index]}”: {hover.c.finding || 'did not run'}
          {hover.c.confidence != null && ` (${pct(hover.c.confidence)})`}; final answer {hover.c.answer}{hover.c.changed ? ' — changed from baseline' : ''}</>
          : <span className="text-muted">Colour = the agent's finding. Outlined = different from its baseline finding. Hover for details, click to compare that run with the baseline.</span>}
      </p>
    </div>
  )
}

/** Two runs side by side: by step (pipeline order) or by agent. */
export function CompareView({ data, colorOf }) {
  const [mode, setMode] = useState('steps')
  const [all, setAll] = useState(false)
  const steps = all ? data.steps : data.steps.filter((s) => s.state !== 'same')
  const changedAgents = (data.agents || []).filter((a) => a.state !== 'same')
  const Head = ({ r, tag }) => (
    <div className="min-w-0 rounded-lg border border-line bg-surface p-3">
      <p className="text-[12.5px] font-semibold text-ink"><span className="mr-1.5 text-muted">{tag}</span>{r.label}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <AnswerChip answer={r.answer} color={colorOf(r.answer)} />
        <span className="text-[12px] tabular-nums text-muted">{pct(r.confidence)}</span>
        {r.review_decision && <ReviewDecision decision={r.review_decision} variant="inline" />}
        {r.trace_id && <Link to={`/traces/${r.trace_id}`} className="text-[12px] font-medium text-primary-700 underline underline-offset-2">Open trace</Link>}
      </div>
    </div>
  )
  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-2"><Head r={data.a} tag="A" /><Head r={data.b} tag="B" /></div>
      <div className="mt-3 rounded-lg border border-line bg-well/60 px-3 py-2 text-[12.5px] text-ink">
        {data.first_divergence ? <>Reasoning first differs at <b>{stepName({ key: data.first_divergence })}</b>
          {' '}(step {(data.steps.findIndex((s) => s.key === data.first_divergence)) + 1} of {data.steps.length}); {data.summary.different} step(s) decided differently, {data.summary.only_a + data.summary.only_b} ran in only one.</>
          : 'Every step made the same decision.'}
        {' '}{changedAgents.length ? <>Agents whose finding changed: <b>{changedAgents.map((a) => agentName(a.agent, a.name)).join(', ')}</b>.</> : 'No agent changed its finding.'}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px]">
        <div role="tablist" className="inline-flex rounded-md border border-line p-0.5">
          {[['steps', 'Step by step'], ['agents', 'Agent by agent']].map(([m, l]) => (
            <button key={m} role="tab" type="button" aria-selected={mode === m} onClick={() => setMode(m)}
              className={cx('rounded px-2.5 py-1 font-medium focus-ring', mode === m ? 'bg-ink text-surface' : 'text-muted hover:text-ink')}>{l}</button>
          ))}
        </div>
        {mode === 'steps' && <label className="ml-auto inline-flex items-center gap-1.5 cursor-pointer text-muted">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="accent-primary-700" />Show identical steps too</label>}
      </div>

      {mode === 'steps' && (
        <ol className="mt-3 space-y-1.5">
          {steps.map((s) => {
            const n = data.steps.indexOf(s) + 1
            return (
              <li key={s.key} className="grid gap-1.5 sm:grid-cols-[170px_minmax(0,1fr)_minmax(0,1fr)]">
                <span className="pt-1.5 text-[12px] font-medium text-muted">
                  <span className="mr-1 tabular-nums text-slate-400">{n}.</span>
                  {s.key === data.first_divergence && <Flag size={12} className="mr-1 inline text-danger-600" aria-hidden />}{stepName(s)}
                </span>
                {[s.a, s.b].map((x, i) => (
                  <div key={i} className={cx('rounded-md border px-2.5 py-1.5 text-[12px]', STATE_STYLE[s.state])}>
                    {x ? <><p className="font-medium text-ink">{x.signature}</p><p className="mt-0.5 line-clamp-2 text-muted">{x.reason}</p></> : <p className="italic text-muted">Step did not run</p>}
                  </div>
                ))}
              </li>
            )
          })}
          {!steps.length && <li className="text-[13px] text-muted">Every step made the same decision in both runs.</li>}
        </ol>
      )}

      {mode === 'agents' && (
        <ol className="mt-3 space-y-1.5">
          {(data.agents || []).map((g) => (
            <li key={g.agent} className="grid gap-1.5 sm:grid-cols-[170px_minmax(0,1fr)_minmax(0,1fr)]">
              <div className="pt-1.5 text-[12px]">
                <p className="font-medium text-ink">{agentName(g.agent, g.name)}</p>
                <p className="text-muted">{g.state === 'same' ? 'same final finding' : g.state === 'different' ? 'final finding changed' : 'ran in one only'}
                  {g.confidence_delta ? `, conf. ${g.confidence_delta > 0 ? '+' : ''}${Math.round(g.confidence_delta * 100)} pts` : ''}</p>
                {g.changed_steps.length > 0 && <p className="text-[11px] text-muted">changed at {g.changed_steps.length} step(s)</p>}
              </div>
              {[g.a, g.b].map((x, i) => (
                <div key={i} className={cx('rounded-md border px-2.5 py-1.5 text-[12px]', g.state === 'same' ? 'border-line' : 'border-warning-500 bg-warning-50/60')}>
                  {x ? <>
                    <div className="flex items-center justify-between gap-2"><AnswerChip answer={x.finding} color={colorOf(x.finding)} /><span className="tabular-nums text-muted">{pct(x.confidence)}{x.pass_number > 1 ? `, pass ${x.pass_number}` : ''}</span></div>
                    {x.n_cited > 0 && <p className="mt-0.5 text-muted">cites {x.n_cited}: {Object.entries(x.cited).map(([l, n]) => `${l} ×${n}`).join(', ')}</p>}
                  </> : <p className="italic text-muted">Agent did not run</p>}
                </div>
              ))}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/** Robustness verdict: plain words, the numbers behind it, and what it does not mean. */
const VERDICT_STYLE = {
  stable: 'border-success-100 bg-success-50', sensitive: 'border-warning-100 bg-warning-50',
  fragile: 'border-danger-100 bg-danger-50', incomplete: 'border-line bg-well',
}
const VERDICT_TITLE = {
  stable: (v) => `Stable under ${v.tested} small disturbances`, sensitive: () => 'Same diagnosis, but shaky',
  fragile: () => 'Fragile — small changes give a different diagnosis', incomplete: () => 'Robustness check still running',
}
export function VerdictBanner({ verdict, caveats, compact }) {
  if (!verdict) return null
  const tone = { stable: 'text-success-700', sensitive: 'text-warning-700', fragile: 'text-danger-700', incomplete: 'text-muted' }[verdict.level]
  return (
    <div className={cx('rounded-lg border px-3 py-2', VERDICT_STYLE[verdict.level])}>
      <p className={cx('font-semibold', tone, compact ? 'text-[12.5px]' : 'text-[13.5px]')}>{VERDICT_TITLE[verdict.level]?.(verdict)}</p>
      <p className="text-[12.5px] leading-snug text-ink">{verdict.text}</p>
      {verdict.level !== 'incomplete' && (
        <p className="mt-1 text-[11.5px] text-muted">
          Tested: each reading ± its typical sensor error, all readings shifted together, and the top cited evidence records left out ({verdict.tested} runs{verdict.failed ? `, ${verdict.failed} failed` : ''}).
          {verdict.confidence_range && ` Confidence across them: ${pct(verdict.confidence_range[0])}–${pct(verdict.confidence_range[1])}.`}
          {verdict.baseline_margin != null && ` Lead over the runner-up: ${verdict.baseline_margin.toFixed(2)} (score points).`}
        </p>
      )}
      {verdict.nearest_flips?.length > 0 && (
        <p className="mt-1 text-[12px] text-ink"><b>Nearest change of diagnosis</b> (wider sweep on out-of-range readings): {verdict.nearest_flips.map((f) => `${f.label} → ${f.answer}`).join('; ')}.</p>
      )}
      {verdict.level !== 'incomplete' && <p className="mt-1 text-[11.5px] text-muted">These are limits of the model and its knowledge base, not equipment limits.</p>}
      {caveats?.length > 0 && (
        <details className="mt-1 text-[11.5px] text-muted"><summary className="cursor-pointer">{caveats.length} caveats</summary>
          <ul className="mt-1 list-disc pl-5">{caveats.map((c) => <li key={c}>{c}</li>)}</ul></details>
      )}
    </div>
  )
}

/** Each stated reading against the knowledge base's normal band. */
export function ReadingsStrip({ sensorView }) {
  const rows = (sensorView || []).filter((s) => s.value != null)
  if (!rows.length) return null
  const fmt = (v) => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumSignificantDigits: 3 }))
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Readings against their normal range">
      {rows.map((s) => {
        const out = s.band_low != null && s.band_high != null && (s.value < s.band_low || s.value > s.band_high)
        const unit = (s.unit || '').replace(/^\((.*)\)$/, '$1')
        return (
          <span key={s.sensor} title={`Normal range ${fmt(s.band_low)}–${fmt(s.band_high)} ${unit}${s.status ? ` · ${s.status}` : ''}`}
            className={cx('inline-flex items-baseline gap-1 rounded-md border px-1.5 py-0.5 text-[11.5px]', out ? 'border-warning-500 bg-warning-50 text-ink' : 'border-line bg-surface text-muted')}>
            <span className="font-medium text-ink">{s.label}</span>
            <span className="tabular-nums">{fmt(s.value)}</span>
            {out && <span className="font-semibold text-warning-700">{s.value > s.band_high ? '▲ above' : '▼ below'} {fmt(s.value > s.band_high ? s.band_high : s.band_low)}</span>}
          </span>
        )
      })}
    </div>
  )
}
