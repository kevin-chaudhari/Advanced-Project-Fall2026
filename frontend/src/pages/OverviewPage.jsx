import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useDiagnostics } from '../state/DiagnosticsContext'
import { getEvaluation } from '../services/api'
import { AGENT_ICON } from '../components/dashboard/StageColumn'
import { agentColor } from '../lib/agentColors'

/*
 * Project overview — the first page. Explains what the system does and how, in plain language.
 * Live figures (record counts, benchmark results) come from the backend; nothing here is invented.
 */

const PIPELINE = [
  { t: 'Read the question', d: 'Pull out the equipment type and every sensor reading given. Channels that were not reported are marked missing and never filled in.' },
  { t: 'Retrieve evidence', d: 'Search the knowledge base four ways (meaning, metadata, numeric similarity, historical outcomes) and rerank. Each record becomes an evidence item with an ID like EV-001.' },
  { t: 'Three independent opinions', d: 'The Diagnostic Expert, Pattern Recognition and Rapid Triage agents analyse the same evidence separately, each with its own method.' },
  { t: 'Challenge the result', d: 'The Verification Analyst checks every candidate against the evidence. Agreement between agents never counts as evidence by itself.' },
  { t: 'Fill gaps', d: 'If evidence is weak or two faults are too close to call, the system retrieves more targeted records and re-runs only the agent that needs it.' },
  { t: 'Measure uncertainty', d: 'The Ambiguity agent computes confidence from visible factors. In hard cases all six agents deliberate in an agent council.' },
  { t: 'Decide and gate', d: 'The Coordinator writes the final answer, unsupported numbers are removed, and eight explicit criteria decide whether a person must review it.' },
]

const AGENTS = [
  { key: 'diagnostic_expert', name: 'Diagnostic Expert', persona: 'Dr. Elena Vasquez, Senior Reliability Engineer', stage: 'Initial analysis', d: 'Generates competing fault hypotheses and lists the supporting, contradicting and missing evidence for each.' },
  { key: 'pattern_agent', name: 'Pattern Recognition', persona: 'Dr. Aisha Patel, Predictive Maintenance Data Scientist', stage: 'Initial analysis', d: 'Compares the readings with the nearest historical cases and flags which channels are anomalous.' },
  { key: 'aggressive_agent', name: 'Rapid Triage', persona: 'Commander Marcus Chen, Rapid Failure Triage Officer', stage: 'Initial analysis', d: 'Applies fast deterministic rules (bands, consistency, signature direction) to produce a quick signal and a severity.' },
  { key: 'verification', name: 'Verification Analyst', persona: 'Priya Raman, Reliability Assurance Lead', stage: 'Verification', d: 'Adversarially tests every candidate against the evidence and keeps only what can be defended.' },
  { key: 'ambiguity', name: 'Ambiguity Detection', persona: 'Dr. Sofia Nakamura, Uncertainty Quantification Specialist', stage: 'Uncertainty', d: 'Measures missing data, conflicts and weak retrieval, and computes the factor-based confidence.' },
  { key: 'human_review_coordinator', name: 'Human Review Coordinator', persona: 'Director Sarah Mitchell, Plant Operations Director', stage: 'Final decision', d: 'Writes the claim-validated final answer and applies the human-review gate.' },
]

const GATE = [
  'Confidence is at least 0.65',
  'The leading fault is at least 0.15 ahead of the runner-up',
  'No sensor consistency rule is broken',
  'A strong historical match exists',
  'No signature channel of the diagnosis is missing',
  'The question contains numeric sensor readings',
  'The diagnosis and every final claim are backed by evidence',
  'Critical severity requires confidence of at least 0.80',
]

const KBS = [
  { id: 'afrb', name: 'AFRB sensor records', d: 'Seven sensor channels per record (temperature, vibration, pressure, RPM, current, voltage, flow) with labelled faults. A clearly labelled synthetic partition adds rare and edge cases.' },
  { id: 'failure_iq', name: 'FailureSensorIQ', d: 'Text knowledge of which failure events relate to which sensors, per equipment type.' },
  { id: 'hydraulic', name: 'Hydraulic test rig (UCI #447)', d: 'Real measured 60-second load cycles with recorded component conditions: temperature, vibration, pressure and flow.' },
]

const STACK = [
  ['Interface', 'React, Vite and Tailwind CSS'],
  ['API', 'FastAPI (Python)'],
  ['Retrieval', 'FAISS vector indexes with MiniLM sentence embeddings, plus numeric and metadata search'],
  ['Agents', 'Six agents on a deterministic orchestration harness; OpenAI or Ollama optional, fully deterministic without an LLM'],
  ['Storage', 'SQLite history of past analyses'],
]

function Section({ id, title, intro, children }) {
  return (
    <section aria-labelledby={id} className="py-12 border-t border-line">
      <div className="grid gap-8 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div>
          <h2 id={id} className="text-[22px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
          {intro && <p className="mt-2 text-[14px] leading-relaxed text-muted">{intro}</p>}
        </div>
        <div className="min-w-0">{children}</div>
      </div>
    </section>
  )
}

const pct = (v, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)

export default function OverviewPage() {
  const nav = useNavigate()
  const { health, latest } = useDiagnostics()
  const [ev, setEv] = useState(null)
  useEffect(() => { getEvaluation().then(setEv).catch(() => setEv(null)) }, [])
  const b = ev?.baseline?.summary, h = ev?.harness_combined?.summary
  const counts = health?.record_counts || {}
  const total = Object.values(counts).reduce((a, c) => a + Object.values(c).reduce((x, y) => x + y, 0), 0)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1240px] px-5 sm:px-8">
        {/* hero */}
        <header className="pt-14 pb-12 grid gap-10 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] items-end">
          <div>
            <p className="text-[14px] font-medium text-primary-700">Industrial predictive maintenance</p>
            <h1 className="mt-3 text-[40px] sm:text-[54px] leading-[1.02] font-semibold tracking-[-0.025em] text-ink">
              Industrial Diagnostic AI
            </h1>
            <p className="mt-5 text-[18px] leading-relaxed text-ink max-w-[60ch]">
              Describe a machine and its sensor readings. Six cooperating AI agents find the most likely fault, show the
              evidence behind it, measure how sure they are, and say plainly when a person needs to check the answer.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <button type="button" className="btn-primary px-5 py-2.5 text-[14px]" onClick={() => nav('/chat')}>Ask a diagnostic question <ArrowRight size={16} aria-hidden /></button>
              <button type="button" className="btn-ghost border border-slate-300 px-5 py-2.5 text-[14px] text-ink" onClick={() => nav('/dashboard')}>
                {latest ? 'See the latest diagnosis' : 'Open the agent dashboard'}
              </button>
            </div>
          </div>
          {/* an example of the kind of question → answer the system produces (illustrative, labelled) */}
          <figure className="card p-5" aria-label="Example of a question and answer">
            <figcaption className="text-[12px] text-muted">Example of how it works</figcaption>
            <p className="mt-2 rounded-lg bg-well px-3.5 py-2.5 text-[13.5px] leading-snug text-ink">
              “Slurry pump: temperature 95 °C, vibration 0.79, pressure 55 PSI, 2400 RPM. What is the most likely fault?”
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5" aria-label="The six agents">
              {AGENTS.map((a) => { const I = AGENT_ICON[a.key]; return <span key={a.key} title={a.name} className="grid h-7 w-7 place-items-center rounded-md text-white" style={{ background: agentColor(a.key) }}><I size={14} /></span> })}
            </div>
            <p className="mt-3 text-[20px] font-semibold text-ink">Bearing wear</p>
            <p className="text-[13px] text-ink">Supported by cited evidence records, with confidence computed from measured factors and an explicit auto-resolve or human-review decision.</p>
          </figure>
        </header>

        <Section id="why" title="Why it exists" intro="Maintenance teams need answers they can trust and check.">
          <div className="grid gap-5 md:grid-cols-3 text-[14px] leading-relaxed text-ink">
            <div><h3 className="font-semibold">Grounded, not guessed</h3><p className="mt-1">Every claim cites an evidence ID. Numbers that cannot be traced to the question, a record or a declared rule are removed before you see the answer.</p></div>
            <div><h3 className="font-semibold">Several viewpoints</h3><p className="mt-1">Three agents analyse independently, a fourth tries to prove them wrong, and a fifth measures what is still uncertain.</p></div>
            <div><h3 className="font-semibold">Honest about doubt</h3><p className="mt-1">Confidence comes from visible factors, and an explicit gate sends unclear or risky cases to a person instead of auto-resolving them.</p></div>
          </div>
        </Section>

        <Section id="how" title="How a question is answered" intro="Every diagnosis passes through the same seven steps. You can watch them on the agent dashboard.">
          <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {PIPELINE.map((p, i) => (
              <li key={p.t} className="card p-4">
                <div className="text-[13px] font-semibold text-primary-700 tabular-nums">Step {i + 1}</div>
                <h3 className="mt-1 text-[15px] font-semibold text-ink">{p.t}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink">{p.d}</p>
              </li>
            ))}
          </ol>
        </Section>

        <Section id="agents" title="The six agents" intro="Each agent has a persona and a fixed method, so their disagreements are informative rather than random.">
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {AGENTS.map((a) => {
              const I = AGENT_ICON[a.key]
              return (
                <li key={a.key} className="card p-4" style={{ boxShadow: `inset 0 3px 0 ${agentColor(a.key)}` }}>
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-9 w-9 place-items-center rounded-lg text-white" style={{ background: agentColor(a.key) }} aria-hidden><I size={18} /></span>
                    <div className="min-w-0">
                      <h3 className="text-[15px] font-semibold" style={{ color: agentColor(a.key) }}>{a.name}</h3>
                      <p className="text-[12px] text-muted truncate">{a.stage}</p>
                    </div>
                  </div>
                  <p className="mt-2.5 text-[13px] leading-relaxed text-ink">{a.d}</p>
                  <p className="mt-2 text-[12px] text-muted">{a.persona}</p>
                </li>
              )
            })}
          </ul>
        </Section>

        <Section id="trust" title="Evidence, confidence and review" intro="The parts that make an answer checkable.">
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-4 text-[14px] leading-relaxed text-ink">
              <div><h3 className="font-semibold">Traceable evidence</h3><p className="mt-1">Retrieved records are numbered EV-001, EV-002 and so on; values the system calculates are numbered D-001 onwards. Each record is labelled REAL or SYNTHETIC so you always know where support comes from.</p></div>
              <div><h3 className="font-semibold">Confidence from factors</h3><p className="mt-1">Evidence quality, separation from the runner-up, historical similarity, data completeness, contradictions, retrieval quality, agent agreement and reliance on synthetic data each pull confidence down when they are weak.</p></div>
              <div><h3 className="font-semibold">Agent council</h3><p className="mt-1">After a short private draft, the six agents work every case out together: they share positions, question and challenge each other, and revise until they agree on a joint finding. Hard cases go on to an escalation council. Their agreed confidence can lower the evidence confidence, never raise it.</p></div>
            </div>
            <div className="card p-5">
              <h3 className="text-[15px] font-semibold text-ink">The human-review gate</h3>
              <p className="mt-1 text-[13px] text-muted">The answer is marked AUTO_RESOLVE only when all eight criteria pass. Otherwise it is REQUIRES_HUMAN_REVIEW, with the failed criteria listed.</p>
              <ol className="mt-3 space-y-1.5">
                {GATE.map((g, i) => (
                  <li key={g} className="grid grid-cols-[30px_minmax(0,1fr)] text-[13px] text-ink">
                    <span className="font-mono text-[12px] text-muted">G{i + 1}</span><span>{g}</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </Section>

        <Section id="data" title="Knowledge bases" intro={health && !health.offline && total ? `${total.toLocaleString()} records loaded on the backend right now.` : 'Record counts appear here when the backend is running.'}>
          <ul className="grid gap-3 md:grid-cols-3">
            {KBS.map((k) => {
              const c = counts[k.id] || {}
              return (
                <li key={k.id} className="card p-4">
                  <h3 className="text-[15px] font-semibold text-ink">{k.name}</h3>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-ink">{k.d}</p>
                  <p className="mt-3 text-[13px] text-ink tabular-nums">
                    {health && !health.offline
                      ? Object.keys(c).length ? Object.entries(c).map(([t, n]) => `${n.toLocaleString()} ${t}`).join(' · ') : 'Not loaded'
                      : <span className="text-muted">Backend not connected</span>}
                  </p>
                </li>
              )
            })}
          </ul>
        </Section>

        {h && b && (
          <Section id="results" title="Measured results" intro="From the project's benchmark of held-out cases, comparing the original pipeline with the current harness.">
            <div className="card overflow-x-auto">
              <table className="w-full text-[14px]">
                <thead className="text-left text-[12.5px] text-muted border-b border-line"><tr><th className="px-5 py-2.5 font-medium">Measure</th><th className="px-3 py-2.5 font-medium text-right">Original pipeline</th><th className="px-5 py-2.5 font-medium text-right">Current harness</th></tr></thead>
                <tbody className="divide-y divide-line tabular-nums">
                  {[['Diagnostic accuracy', 'diagnostic_accuracy'], ['Accuracy on held-out real records', 'accuracy_real_holdout'], ['Unsupported numeric claims', 'hallucination_rate'], ['Retrieval hit@5', 'retrieval_hit_at5']]
                    .filter(([, k]) => h[k] != null || b[k] != null)
                    .map(([label, k]) => <tr key={k}><td className="px-5 py-2.5">{label}</td><td className="px-3 py-2.5 text-right">{pct(b[k])}</td><td className="px-5 py-2.5 text-right font-semibold">{pct(h[k])}</td></tr>)}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={() => nav('/analysis')} className="mt-3 inline-flex items-center gap-1 text-[13.5px] font-medium text-primary-700 hover:text-ink focus-ring rounded">All data and evaluation results <ArrowRight size={14} aria-hidden /></button>
          </Section>
        )}

        <Section id="stack" title="How it is built">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[140px_minmax(0,1fr)] text-[14px]">
            {STACK.map(([k, v]) => <div key={k} className="contents"><dt className="font-semibold text-ink">{k}</dt><dd className="text-ink">{v}</dd></div>)}
          </dl>
        </Section>

        <Section id="use" title="Using it">
          <ol className="grid gap-3 md:grid-cols-3">
            {[
              ['Pick a dataset', 'Choose AFRB sensors, FailureSensorIQ or the hydraulic rig in the top bar, and real, synthetic or combined data in the chat.'],
              ['Ask in Diagnostic chat', 'Give the readings you have. Examples are there to start from. The full answer, agent reasoning and evidence appear in the conversation.'],
              ['Review on the dashboard', 'The agent dashboard shows the latest diagnosis as the pipeline that produced it. Maximize any stage for the full detail.'],
            ].map(([t, d], i) => (
              <li key={t} className="card p-4">
                <div className="text-[13px] font-semibold text-primary-700">Step {i + 1}</div>
                <h3 className="mt-1 text-[15px] font-semibold text-ink">{t}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink">{d}</p>
              </li>
            ))}
          </ol>
          <div className="mt-6 flex flex-wrap gap-3 pb-6">
            <button type="button" className="btn-primary px-5 py-2.5 text-[14px]" onClick={() => nav('/chat')}>Ask a diagnostic question <ArrowRight size={16} aria-hidden /></button>
          </div>
        </Section>
      </div>
    </div>
  )
}
