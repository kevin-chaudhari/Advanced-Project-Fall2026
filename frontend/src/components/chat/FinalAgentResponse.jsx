import { lazy, Suspense, useState } from 'react'
import { Wrench, ShieldAlert, CheckCircle2, Loader2 } from 'lucide-react'
import { cx, Cited } from '../ui'
import { ConfidenceIndicator, ReviewDecision, Disclosure, ProvenanceBar } from '../primitives'
import EvidenceExplorer from '../EvidenceExplorer'
import AgentResponseAccordion from './AgentResponseAccordion'
import {
  VerificationDetail, verificationMeta, FeedbackDetail, feedbackMeta, CouncilDetail, councilMeta, GateDetail,
} from '../diagnosis/details'

// The existing deep-analysis views are kept intact and only loaded when opened.
const DecisionExplorer = lazy(() => import('../DecisionExplorer'))
const DiagnosisReport = lazy(() => import('../DiagnosisReport'))

const FACTOR_LABEL = {
  evidence_quality: 'Evidence quality', hypothesis_separation: 'Separation from runner-up', historical_similarity: 'Historical similarity',
  data_completeness: 'Data completeness', contradictions: 'Free of contradictions', retrieval_quality: 'Retrieval quality',
  agent_agreement: 'Agent agreement', synthetic_reliance: 'Real-data support',
}

function Section({ n, title, children, className }) {
  return (
    <section className={cx('grid gap-x-4 gap-y-1.5 sm:grid-cols-[148px_minmax(0,1fr)] py-4 border-t border-line first:border-t-0', className)}>
      <h4 className="flex items-baseline gap-2 text-[12.5px] font-medium text-muted">
        <span className="font-mono text-[11px] text-slate-400 tabular-nums" aria-hidden>{n}</span>{title}
      </h4>
      <div className="min-w-0">{children}</div>
    </section>
  )
}

function Inner({ title, meta, children, defaultOpen }) {
  return (
    <Disclosure defaultOpen={defaultOpen} headerClass="py-1 -ml-1 px-1 hover:bg-well/60"
      title={<span className="text-[12.5px] font-medium text-ink">{title}</span>} meta={meta} bodyClass="mt-1.5 mb-1 ml-5">
      {children}
    </Disclosure>
  )
}

/** The coordinator's answer, organised into the eight reading sections. Technical depth is opt-in. */
export default function FinalAgentResponse({ s, result, question }) {
  const [focus, setFocus] = useState(null)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [deep, setDeep] = useState(null) // 'explorer' | 'report' | null
  const onEvidence = (id) => { setEvidenceOpen(true); setFocus(id) }
  const factors = [...s.confidenceFactors].sort((a, b) => a.value - b.value)
  const amb = s.ambiguity
  const insufficient = s.label === 'Insufficient Evidence'

  return (
    <article className="card overflow-hidden">
      {/* conclusion header */}
      <header className={cx('grid gap-5 p-5 sm:p-6 md:grid-cols-[minmax(0,1fr)_220px] border-b border-line',
        insufficient ? 'bg-danger-50/40' : s.needsReview ? 'bg-warning-50/50' : 'bg-success-50/40')}>
        <div className="min-w-0">
          <div className="text-[12.5px] text-muted">Coordinator's diagnosis</div>
          <h3 className="mt-1 text-[24px] sm:text-[28px] leading-tight font-semibold tracking-[-0.015em] first-letter:uppercase break-words">{s.label || s.answer || 'No diagnosis returned'}</h3>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
            <span><b className="text-ink tabular-nums">{s.evidenceCount}</b> evidence records</span>
            {s.provenance && <span className="tabular-nums">{s.provenance.real ?? 0} real, {s.provenance.synthetic ?? 0} synthetic</span>}
            {s.latencyMs != null && <span className="tabular-nums">{Math.round(s.latencyMs)} ms</span>}
            {s.llmMode && <span>{s.llmMode}</span>}
          </div>
        </div>
        <div className="flex md:flex-col items-center md:items-stretch gap-4">
          <div className="shrink-0 md:self-end"><ReviewDecision decision={s.decision} /></div>
          <div className="flex-1"><ConfidenceIndicator value={s.confidence} threshold={s.reviewThreshold} /></div>
        </div>
      </header>

      <div className="px-5 sm:px-6">
        <Section n="1" title="Conclusion">
          <p className="text-[15px] font-medium leading-snug text-ink">{s.answer || <span className="text-muted">No direct answer returned.</span>}</p>
        </Section>

        <Section n="2" title="Explanation">
          <p className="text-[14px] leading-relaxed text-ink"><Cited text={s.explanation} onEvidence={onEvidence} /></p>
        </Section>

        <Section n="3" title="Supporting evidence">
          {s.supportingStatements.length ? (
            <ul className="space-y-1.5 text-[13px] leading-snug text-ink">
              {s.supportingStatements.map((t, i) => <li key={i} className="pl-3 border-l-2 border-success-500/40"><Cited text={t} onEvidence={onEvidence} /></li>)}
            </ul>
          ) : <p className="text-[13px] text-muted">No supporting statements were returned.</p>}
          <div className="mt-3 max-w-sm"><ProvenanceBar composition={s.provenance} /></div>
          {s.evidence.length > 0 && (
            <Disclosure open={evidenceOpen} onToggle={setEvidenceOpen} className="mt-3"
              headerClass="py-1 -ml-1 px-1 hover:bg-well/60" title={<span className="text-[12.5px] font-medium text-ink">All evidence records</span>}
              meta={`${s.evidence.length}`} bodyClass="mt-2">
              <EvidenceExplorer harness={result.harness} focusId={focus} />
            </Disclosure>
          )}
        </Section>

        <Section n="4" title="Agent perspectives">
          <AgentResponseAccordion agents={s.agents} onEvidence={onEvidence} />
        </Section>

        <Section n="5" title="Confidence and uncertainty">
          <p className="text-[13px] text-ink">
            Measured confidence <b className="font-semibold tabular-nums">{s.confidence != null ? `${Math.round(s.confidence * 100)}%` : '—'}</b>
            {amb?.ambiguity_level && <>, ambiguity <b className="font-semibold">{amb.ambiguity_level.toLowerCase()}</b></>}.
            {factors[0] && <span className="text-muted"> Weakest factor: {FACTOR_LABEL[factors[0].name] || factors[0].name} ({factors[0].value.toFixed(2)}).</span>}
          </p>
          {amb?.flags?.length > 0 && (
            <ul className="mt-2 space-y-1 text-[12.5px] text-warning-700">{amb.flags.map((f, i) => <li key={i} className="pl-3 border-l-2 border-warning-500/50">{f}</li>)}</ul>
          )}
          {factors.length > 0 && (
            <Inner title="Confidence factors" meta={`${factors.length}`}>
              <ul className="space-y-1.5">
                {factors.map((f) => (
                  <li key={f.name} className="grid grid-cols-[150px_80px_36px_minmax(0,1fr)] items-center gap-2 text-[12px] max-sm:grid-cols-[minmax(0,1fr)_60px_36px]">
                    <span className="truncate text-ink">{FACTOR_LABEL[f.name] || f.name}</span>
                    <span className="h-1 rounded-full bg-well overflow-hidden" aria-hidden>
                      <span className={cx('block h-full rounded-full', f.value >= 0.8 ? 'bg-success-500' : f.value >= 0.5 ? 'bg-warning-500' : 'bg-danger-500')} style={{ width: `${f.value * 100}%` }} />
                    </span>
                    <span className="tabular-nums text-muted text-right">{f.value.toFixed(2)}</span>
                    <span className="text-muted truncate max-sm:col-span-3" title={f.explanation}>{f.explanation}</span>
                  </li>
                ))}
              </ul>
            </Inner>
          )}
        </Section>

        <Section n="6" title="Verification">
          <p className="text-[13px] text-ink">{verificationMeta(s)}{s.verification?.verified_label ? `: ${s.verification.verified_label}` : ''}.</p>
          <div className="mt-1.5 space-y-0.5">
            <Inner title="Adversarial review and claim validation"><VerificationDetail s={s} onEvidence={onEvidence} /></Inner>
            <Inner title="Targeted retrieval" meta={feedbackMeta(s)}><FeedbackDetail s={s} onEvidence={onEvidence} /></Inner>
            {s.council && <Inner title="Agent council" meta={councilMeta(s)}><CouncilDetail s={s} /></Inner>}
          </div>
        </Section>

        {s.recommendation && (
          <Section n="7" title="Next action">
            <p className="flex gap-2 text-[13.5px] leading-snug text-ink">
              <Wrench size={15} className="mt-0.5 shrink-0 text-primary-600" aria-hidden /><Cited text={s.recommendation} onEvidence={onEvidence} />
            </p>
          </Section>
        )}

        <Section n={s.recommendation ? '8' : '7'} title="Human review">
          {s.needsReview ? (
            <div className="flex gap-2 text-[13px] text-warning-700">
              <ShieldAlert size={15} className="mt-0.5 shrink-0" aria-hidden />
              <div>
                <b className="font-semibold">A person must review this before acting.</b>
                {s.reviewReasons.length > 0 && <ul className="mt-1 space-y-0.5 text-[12.5px] text-ink">{s.reviewReasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
              </div>
            </div>
          ) : s.decision ? (
            <p className="flex items-center gap-2 text-[13px] text-success-700"><CheckCircle2 size={15} aria-hidden /> <b className="font-semibold">All gate criteria passed; safe to auto-resolve.</b></p>
          ) : <p className="text-[13px] text-muted">No review decision returned.</p>}
          {s.criteria.length > 0 && <div className="mt-1.5"><Inner title="Gate criteria" meta={`${s.criteriaPassed}/${s.criteria.length} passed`}><GateDetail s={s} /></Inner></div>}
        </Section>
      </div>

      {/* existing deep-analysis views, unchanged in function */}
      <footer className="border-t border-line bg-well/40 px-5 sm:px-6 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12.5px] text-muted mr-1">Full technical analysis</span>
          {[['explorer', 'Decision explorer'], ['report', 'Detailed report']].map(([id, label]) => (
            <button key={id} type="button" aria-pressed={deep === id} onClick={() => setDeep(deep === id ? null : id)}
              className={cx('rounded-md border px-2.5 py-1 text-[12px] font-medium focus-ring transition-colors',
                deep === id ? 'border-ink bg-ink text-surface' : 'border-line bg-surface text-ink hover:border-slate-300')}>
              {label}
            </button>
          ))}
        </div>
        {deep && (
          <div className="mt-3">
            <Suspense fallback={<p className="flex items-center gap-2 text-[12.5px] text-muted"><Loader2 size={14} className="animate-spin" /> Loading…</p>}>
              {deep === 'explorer' ? <DecisionExplorer result={result} question={question} /> : <DiagnosisReport result={result} />}
            </Suspense>
          </div>
        )}
      </footer>
    </article>
  )
}
