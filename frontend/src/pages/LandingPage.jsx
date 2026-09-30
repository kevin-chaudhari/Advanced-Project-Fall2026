import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity, Database, ArrowRight, GitBranch, ShieldCheck, Search, FileCheck2 } from 'lucide-react'
import AppShell from '../components/AppShell'
import { StatTile, pct, fmtNum } from '../components/ui'
import { checkHealth, getEvaluation } from '../services/api'

const STAGES = [
  { t: 'Query preparation', d: 'readings, missing channels, equipment', k: 'stage' },
  { t: 'Multi-stage RAG', d: 'semantic · metadata · numeric · historical', k: 'stage' },
  { t: 'Diagnostic Expert · Pattern · Rapid Triage', d: 'three independent perspectives', k: 'agent' },
  { t: 'Verification', d: 'adversarial, evidence-first', k: 'agent' },
  { t: 'Evidence check → targeted RAG ↻', d: 're-run only the affected agent', k: 'loop' },
  { t: 'Ambiguity', d: 'measured uncertainty & confidence', k: 'agent' },
  { t: 'Final coordinator + review gate', d: 'claim-validated answer, explicit criteria', k: 'agent' },
]

export default function LandingPage() {
  const nav = useNavigate()
  const [health, setHealth] = useState(null)
  const [ev, setEv] = useState(null)
  useEffect(() => { checkHealth().then(setHealth).catch(() => setHealth({ offline: true })); getEvaluation().then(setEv).catch(() => {}) }, [])
  const afrb = health?.record_counts?.afrb || {}
  const fiq = health?.record_counts?.failure_iq || {}
  const h = ev?.harness_combined?.summary, b = ev?.baseline?.summary

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto px-6 py-10 space-y-8">
        <section>
          <div className="eyebrow text-primary-700">Industrial predictive maintenance</div>
          <h1 className="text-3xl font-semibold tracking-tight mt-1">Evidence-grounded fault diagnosis with six cooperating agents</h1>
          <p className="text-muted mt-2 max-w-3xl">The same six agents as before, now working through a shared diagnostic state: every claim cites an
            evidence ID, weak evidence triggers targeted retrieval, unsupported statements are removed, and an explicit gate decides when a human must review.</p>
          <div className="flex gap-2 mt-4">
            <button className="btn-primary" onClick={() => nav('/diagnose/afrb')}>Start a diagnosis <ArrowRight size={15} /></button>
            <button className="btn-ghost border border-line" onClick={() => nav('/analysis')}>Data & evaluation</button>
          </div>
        </section>

        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Real AFRB records" value={fmtNum(afrb.real, 0)} accent="text-primary-700" />
          <StatTile label="Synthetic records" value={fmtNum(afrb.synthetic, 0)} accent="text-secondary-700" hint="labelled, separate index" />
          <StatTile label="Accuracy (held-out)" value={h ? pct(h.diagnostic_accuracy) : '—'} hint={b ? `original pipeline ${pct(b.diagnostic_accuracy)}` : 'run the benchmark'} />
          <StatTile label="Unsupported numeric claims" value={h ? pct(h.hallucination_rate, 1) : '—'} hint={b ? `original pipeline ${pct(b.hallucination_rate, 1)}` : ''} />
        </section>

        <section className="card p-5">
          <div className="flex items-center gap-2 mb-4"><GitBranch size={16} className="text-primary-600" /><h2 className="section-title">Orchestration harness</h2></div>
          <ol className="grid gap-2 md:grid-cols-7">
            {STAGES.map((s, i) => (
              <li key={s.t} className={`rounded-lg border p-3 ${s.k === 'agent' ? 'border-primary-200 bg-primary-50/60' : s.k === 'loop' ? 'border-secondary-100 bg-secondary-50/70' : 'border-line bg-white'}`}>
                <div className="text-[11px] text-muted">{i + 1}</div>
                <div className="text-[12px] font-semibold text-ink leading-snug">{s.t}</div>
                <div className="text-[11px] text-muted mt-1 leading-snug">{s.d}</div>
              </li>
            ))}
          </ol>
          <div className="grid gap-4 md:grid-cols-3 mt-5 text-[12px] text-muted">
            <div className="flex gap-2"><Search size={16} className="text-primary-600 shrink-0" />Evidence objects with stable IDs (EV-001…) and REAL / SYNTHETIC provenance on every record.</div>
            <div className="flex gap-2"><FileCheck2 size={16} className="text-primary-600 shrink-0" />Claim validation: every number must trace to the query, a record, a derived value or a declared rule.</div>
            <div className="flex gap-2"><ShieldCheck size={16} className="text-primary-600 shrink-0" />Confidence from measured factors; agreement never substitutes for evidence.</div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          {[
            { id: 'afrb', icon: Activity, t: 'AFRB sensor diagnosis', d: 'Seven sensor channels per record. Real, synthetic or combined knowledge base.', c: afrb, ok: health?.afrb_loaded },
            { id: 'failure_iq', icon: Database, t: 'FailureSensorIQ relevance', d: 'Which failure events relate to which sensors, per equipment type (text knowledge base).', c: fiq, ok: health?.failure_iq_loaded },
          ].map(({ id, icon: Icon, t, d, c, ok }) => (
            <button key={id} onClick={() => nav(`/diagnose/${id}`)} className="card p-5 text-left hover:shadow-lift transition-shadow">
              <div className="flex items-center justify-between"><Icon size={18} className="text-primary-600" /><span className={`text-[11px] ${ok ? 'text-success-700' : 'text-warning-700'}`}>{health?.offline ? 'backend offline' : ok ? '● ready' : '● not loaded'}</span></div>
              <div className="font-semibold mt-3">{t}</div>
              <p className="text-[13px] text-muted mt-1">{d}</p>
              <div className="text-[12px] text-muted mt-3">{fmtNum(c.real ?? 0, 0)} real · {fmtNum(c.synthetic ?? 0, 0)} synthetic</div>
            </button>
          ))}
        </section>
      </div>
    </AppShell>
  )
}
