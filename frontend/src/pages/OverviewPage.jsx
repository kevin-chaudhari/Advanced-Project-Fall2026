import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Eye, MessagesSquare, ShieldCheck, Waypoints, FileSearch, Gauge, Cpu, GitCommitHorizontal, ListOrdered, Database, Activity, UserCheck } from 'lucide-react'
import { useDiagnostics } from '../state/DiagnosticsContext'
import { getEvaluation } from '../services/api'
import { AGENT_ICON } from '../components/dashboard/StageColumn'
import { agentColor } from '../lib/agentColors'
import Council3D from '../components/overview/Council3D'
import { ArchitectureDiagram, ExposureLadder, LifecycleDiagram, MessageLifecycle, OPENNESS, PoolingDiagram } from '../components/overview/Diagrams'

/*
 * Overview — the first page. Explains what Mission Control is, what it observes and how.
 * Diagrams and the 3D scene are explanatory; live figures (record counts, benchmark results)
 * come from the backend and nothing here is invented.
 */

const PROBLEMS = [
  { icon: MessagesSquare, t: 'Opaque conversations', d: 'Autonomous agents message each other, change their minds and settle disputes. Without a record, nobody can say who convinced whom, or whether a message was ever read.' },
  { icon: FileSearch, t: 'Evidence that may not have been used', d: 'Retrieving a record is not the same as an agent seeing it, and seeing it is not the same as relying on it. Most logs blur these together.' },
  { icon: Gauge, t: 'Confidence without accountability', d: 'A single number hides where it came from. A reviewer needs the factors, the score changes and the reason a case was or was not sent to a person.' },
]

const PILLARS = [
  { icon: Eye, t: 'Observe', d: 'Record what actually happened, from observable facts only: every event in order, every message and who read it, every model call, every score change.' },
  { icon: Waypoints, t: 'Explain', d: 'Turn the record into views a person can follow: who talked to whom, how positions moved round by round, where each piece of evidence went.' },
  { icon: UserCheck, t: 'Oversee', d: 'Keep the human in charge: explicit review criteria, visible uncertainty, and traces that can be exported and audited by someone else.' },
]

const AGENTS = [
  { key: 'diagnostic_expert', name: 'Diagnostic Expert', persona: 'Dr. Elena Vasquez, Senior Reliability Engineer', stage: 'Draft · collaboration · council', d: 'Generates competing fault hypotheses and lists the supporting, contradicting and missing evidence for each. Re-scores contested pairs on the channels that tell them apart.' },
  { key: 'pattern_agent', name: 'Pattern Recognition', persona: 'Dr. Aisha Patel, Predictive Maintenance Data Scientist', stage: 'Draft · collaboration · council', d: 'Compares the readings with the nearest historical cases and flags which channels are anomalous.' },
  { key: 'aggressive_agent', name: 'Rapid Triage', persona: 'Commander Marcus Chen, Rapid Failure Triage Officer', stage: 'Draft · collaboration · council', d: 'Applies fast deterministic rules (bands, consistency, signature direction) for a quick signal and a severity. Never drops a safety signal.' },
  { key: 'verification', name: 'Verification Analyst', persona: 'Priya Raman, Reliability Assurance Lead', stage: 'Collaboration · verification', d: 'Adversarially tests every claim against the cited evidence and answers each verification request.' },
  { key: 'ambiguity', name: 'Ambiguity Detection', persona: 'Dr. Sofia Nakamura, Uncertainty Quantification Specialist', stage: 'Uncertainty · council', d: 'Measures missing data, conflicts and weak retrieval, computes the factor-based confidence and raises the uncertainty flags that can convene the escalation council.' },
  { key: 'human_review_coordinator', name: 'Human Review Coordinator', persona: 'Director Sarah Mitchell, Plant Operations Director', stage: 'Synthesis · review gate', d: 'Writes the claim-validated final answer from the board and applies the human-review gate.' },
]

const RECORDED = [
  { icon: ListOrdered, t: 'Event timeline', d: 'An append-only log with a sequence number per trace, safe under concurrent runs. Duplicate observations are no-ops.' },
  { icon: MessagesSquare, t: 'Messages and reads', d: 'Sender, recipients, type, evidence IDs, reply chain, the position stated, and each observed read.' },
  { icon: Activity, t: 'Agent executions', d: 'Input summary, the exact rendered model input, output, confidence, hypotheses, claims, messages sent and read.' },
  { icon: Cpu, t: 'Model calls', d: 'The complete raw response, token usage, finish reason, model and response metadata. Never the API key or headers.' },
  { icon: Database, t: 'Evidence', d: 'Full content of every retrieved record and computed value, with provenance (REAL or SYNTHETIC) and retrieval method.' },
  { icon: Gauge, t: 'Score changes', d: 'Hypothesis scores and confidence immediately before and after every blend and re-score, with the change per hypothesis.' },
  { icon: Waypoints, t: 'Hypothesis states', d: 'Proposed, retained, challenged, modified, rejected, final, per agent, with the message that caused each change.' },
  { icon: GitCommitHorizontal, t: 'Code version', d: 'Git commit, branch, uncommitted changes and a hash of the backend source, so a run can be matched to its implementation.' },
]

const PRINCIPLES = [
  ['Observable only', 'A fact is recorded when it is seen happening, never inferred afterwards.'],
  ['Delivery is not use', 'A message counts as read only when the recipient actually read it; a record counts as used only when it was cited.'],
  ['UNKNOWN, not a guess', 'When something cannot be established, the trace says UNKNOWN or NOT_APPLICABLE.'],
  ['Raw and derived kept apart', 'Graphs, summaries and agreement views are computed from the raw rows and can be recomputed at any time.'],
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
  { id: 'afrb', name: 'AFRB sensor records', d: 'Seven sensor channels per record (temperature, vibration, pressure, RPM, current, voltage, flow) with labelled faults, plus a clearly labelled synthetic partition for rare and edge cases.' },
  { id: 'failure_iq', name: 'FailureSensorIQ', d: 'Text knowledge of which failure events relate to which sensors, per equipment type. Real records only.' },
  { id: 'hydraulic', name: 'Hydraulic test rig (UCI #447)', d: 'Real measured 60-second load cycles with recorded component conditions. Real records only, so questions here use the real partition.' },
]

const STACK = [
  ['Interface', 'React, Vite and Tailwind CSS; the 3D scene is plain canvas'],
  ['API', 'FastAPI (Python), read-only trace endpoints and file exports'],
  ['Retrieval', 'FAISS vector indexes with MiniLM sentence embeddings, plus numeric and metadata search'],
  ['Agents', 'Six agents on a deterministic orchestration harness; OpenAI or Ollama optional (council voicing defaults to gpt-4.1), fully deterministic without an LLM'],
  ['Observability', 'AgentTrace (schema ida.agenttrace/1.1) in SQLite: append-only events, write-through, survives restarts'],
]

function Section({ id, eyebrow, title, intro, children }) {
  return (
    <section aria-labelledby={id} className="py-12 border-t border-line">
      <div className="grid gap-8 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div>
          {eyebrow && <p className="text-[12.5px] font-medium text-primary-700">{eyebrow}</p>}
          <h2 id={id} className="mt-1 text-[22px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
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
        <header className="pt-14 pb-12 grid gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] items-center">
          <div>
            <p className="text-[14px] font-medium text-primary-700">Observability for autonomous multi-agent systems</p>
            <h1 className="mt-3 text-[40px] sm:text-[54px] leading-[1.02] font-semibold tracking-[-0.025em] text-ink">
              Mission Control for Agentic AI
            </h1>
            <p className="mt-4 text-[19px] sm:text-[21px] leading-snug font-medium text-muted max-w-[46ch]">
              An Observability Framework for Human Oversight of Autonomous Multi-Agent Systems
            </p>
            <p className="mt-5 text-[16.5px] leading-relaxed text-ink max-w-[62ch]">
              When several AI agents work a problem out together, the answer is only as trustworthy as your ability to see
              how they reached it. Mission Control records every message, every piece of evidence an agent actually saw,
              every model call and every score change, explains them in views a person can follow, and keeps a human in
              charge of the final decision.
            </p>
            <p className="mt-3 text-[14.5px] leading-relaxed text-muted max-w-[62ch]">
              The system it observes here is a six-agent council that diagnoses industrial equipment faults from sensor readings.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <button type="button" className="btn-primary px-5 py-2.5 text-[14px]" onClick={() => nav('/chat')}>Ask a diagnostic question <ArrowRight size={16} aria-hidden /></button>
              <button type="button" className="btn-ghost border border-slate-300 px-5 py-2.5 text-[14px] text-ink" onClick={() => nav('/traces')}>Open the Trace explorer</button>
              {latest && <button type="button" className="btn-ghost px-3 py-2.5 text-[14px]" onClick={() => nav('/dashboard')}>Latest diagnosis</button>}
            </div>
          </div>

          <figure className="card overflow-hidden">
            <div className="h-[340px] sm:h-[380px] bg-canvas">
              <Council3D />
            </div>
            <figcaption className="border-t border-line px-4 py-3 text-[12.5px] leading-snug text-muted">
              Illustration: the six agents exchange messages on the council ring; each delivered message travels to the
              AgentTrace core, where it is recorded for the human operator. Drag to rotate.
            </figcaption>
          </figure>
        </header>

        <Section id="problem" eyebrow="Why it exists" title="The oversight problem" intro="Multi-agent systems make decisions through conversation. Oversight needs that conversation to be visible.">
          <div className="grid gap-4 md:grid-cols-3">
            {PROBLEMS.map(({ icon: I, t, d }) => (
              <div key={t} className="card p-4">
                <I size={18} className="text-danger-600" aria-hidden />
                <h3 className="mt-2 text-[15px] font-semibold text-ink">{t}</h3>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink">{d}</p>
              </div>
            ))}
          </div>
          <h3 className="mt-8 text-[15px] font-semibold text-ink">What Mission Control does about it</h3>
          <div className="mt-3 grid gap-4 md:grid-cols-3">
            {PILLARS.map(({ icon: I, t, d }, i) => (
              <div key={t} className="card p-4" style={{ boxShadow: 'inset 0 3px 0 #A68A64' }}>
                <div className="flex items-center gap-2">
                  <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary-50 text-primary-700" aria-hidden><I size={16} /></span>
                  <span className="text-[12px] font-semibold text-primary-700 tabular-nums">{i + 1}</span>
                  <h4 className="text-[15px] font-semibold text-ink">{t}</h4>
                </div>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink">{d}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section id="architecture" eyebrow="How it fits together" title="Architecture" intro="The recorder sits beside the agents, not inside their decisions: it observes and stores, and changes nothing the agents do.">
          <div className="card p-4 sm:p-5">
            <ArchitectureDiagram />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-3 text-[13.5px] leading-relaxed text-ink">
            <p><span className="font-semibold">System under observation.</span> The orchestration harness runs the six agents over a knowledge base of real and synthetic records and produces a diagnosis.</p>
            <p><span className="font-semibold">Observability layer.</span> AgentTrace writes every step to an append-only SQLite store as it happens, so a trace reads the same after a restart.</p>
            <p><span className="font-semibold">Human interface.</span> Mission Control reads the trace through a read-only API: dashboards, the conversation, the Trace explorer and downloadable files.</p>
          </div>
        </Section>

        <Section id="agents" eyebrow="The system under observation" title="The six agents" intro="Each agent has a persona and a fixed method, so their disagreements are informative rather than random.">
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

        <Section id="lifecycle" eyebrow="Step by step" title="The life of one question" intro="Every diagnosis follows the same path. Dashed steps run only when the case needs them. Each step lists what the trace records.">
          <LifecycleDiagram />
        </Section>

        <Section id="council" eyebrow="Breaking the independence" title="How the agents reach agreement" intro="After a private draft, agents read each other's positions and update their own beliefs. How far each one moves is part of its persona.">
          <div className="card p-4 sm:p-5">
            <h3 className="text-[15px] font-semibold text-ink">One belief update, worked through</h3>
            <p className="mt-1 text-[13px] text-muted">An illustration with made-up numbers. Each agent combines its own evidence view with the positions it actually read, weighted by its openness α.</p>
            <div className="mt-4"><PoolingDiagram /></div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="card p-4 sm:p-5">
              <h3 className="text-[15px] font-semibold text-ink">Openness α by persona</h3>
              <ul className="mt-3 space-y-3">
                {OPENNESS.map((o) => (
                  <li key={o.key}>
                    <div className="flex items-baseline justify-between gap-3 text-[13px]">
                      <span className="font-semibold" style={{ color: agentColor(o.key) }}>{AGENTS.find((a) => a.key === o.key).name}</span>
                      <span className="tabular-nums text-ink">{o.a.toFixed(2)}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-well"><div className="h-1.5 rounded-full" style={{ width: `${o.a * 100}%`, background: agentColor(o.key) }} /></div>
                    <p className="mt-1 text-[12px] text-muted">{o.why}</p>
                  </li>
                ))}
              </ul>
            </div>
            <div className="card p-4 sm:p-5 space-y-4 text-[13.5px] leading-relaxed text-ink">
              <div>
                <h3 className="text-[15px] font-semibold">Critique and convergence</h3>
                <p className="mt-1">An agent challenges a peer whose leading fault it cannot support. Rounds continue, up to three, until every agent has the same leading fault and no belief moves by more than 0.02. The joint finding is the geometric mean of the final positions.</p>
              </div>
              <div>
                <h3 className="text-[15px] font-semibold">Confidence the evidence can cap</h3>
                <p className="mt-1">Council confidence is the agents' mean belief in the joint finding. The final confidence is</p>
                <p className="mt-1.5 rounded-lg bg-well px-3 py-2 font-mono text-[12.5px]">final = min(evidence, (1 − β)·evidence + β·council)</p>
                <p className="mt-1.5">so agreement can lower confidence but never raise it above what the evidence supports.</p>
              </div>
              <div>
                <h3 className="text-[15px] font-semibold">What “resolved” means</h3>
                <p className="mt-1">A challenge is marked resolved when the two agents end on the same leading fault. That is label alignment, not proof of strong agreement, so the trace keeps both agents' beliefs before and after for you to judge.</p>
              </div>
            </div>
          </div>
        </Section>

        <Section id="trace" eyebrow="The observability layer" title="What AgentTrace records" intro="Everything below is written while the run happens and can be downloaded as JSON, a readable transcript or CSV tables.">
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {RECORDED.map(({ icon: I, t, d }) => (
              <li key={t} className="card p-4">
                <I size={17} className="text-primary-700" aria-hidden />
                <h3 className="mt-2 text-[14.5px] font-semibold text-ink">{t}</h3>
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink">{d}</p>
              </li>
            ))}
          </ul>

          <h3 className="mt-8 text-[15px] font-semibold text-ink">How far a piece of evidence got</h3>
          <p className="mt-1 text-[13px] text-muted max-w-[70ch]">Each record is placed on a ladder of observed exposure. Reaching one level never implies the next.</p>
          <div className="mt-3"><ExposureLadder /></div>

          <h3 className="mt-8 text-[15px] font-semibold text-ink">How a message is followed</h3>
          <div className="mt-3"><MessageLifecycle /></div>

          <div className="mt-8 grid gap-3 md:grid-cols-2">
            {PRINCIPLES.map(([t, d]) => (
              <div key={t} className="rounded-lg border border-line bg-well/60 px-4 py-3">
                <h4 className="text-[13.5px] font-semibold text-ink">{t}</h4>
                <p className="mt-0.5 text-[13px] leading-relaxed text-ink">{d}</p>
              </div>
            ))}
          </div>
          <button type="button" onClick={() => nav('/traces')} className="mt-5 inline-flex items-center gap-1 text-[13.5px] font-medium text-primary-700 hover:text-ink focus-ring rounded">Explore a real trace <ArrowRight size={14} aria-hidden /></button>
        </Section>

        <Section id="oversight" eyebrow="The human stays in charge" title="Human oversight" intro="The system decides when it may answer on its own, and shows a person why.">
          <div className="grid gap-6 lg:grid-cols-2">
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
            <div className="space-y-4 text-[14px] leading-relaxed text-ink">
              <div className="flex gap-3"><ShieldCheck size={18} className="mt-0.5 shrink-0 text-success-600" aria-hidden /><div><h3 className="font-semibold">Grounded answers</h3><p className="mt-0.5">Every claim cites an evidence ID. Numbers that cannot be traced to the question, a record or a declared rule are removed before you see the answer.</p></div></div>
              <div className="flex gap-3"><Gauge size={18} className="mt-0.5 shrink-0 text-success-600" aria-hidden /><div><h3 className="font-semibold">Visible uncertainty</h3><p className="mt-0.5">Confidence is broken into its factors, and evidence, council and final confidence are shown side by side.</p></div></div>
              <div className="flex gap-3"><Eye size={18} className="mt-0.5 shrink-0 text-success-600" aria-hidden /><div><h3 className="font-semibold">Inspect before you approve</h3><p className="mt-0.5">The Trace explorer shows how the agents agreed, every message and who read it, score changes, evidence flow and raw events.</p></div></div>
              <div className="flex gap-3"><FileSearch size={18} className="mt-0.5 shrink-0 text-success-600" aria-hidden /><div><h3 className="font-semibold">Hand it to someone else</h3><p className="mt-0.5">Any trace downloads as JSON, a Markdown transcript or CSV tables, stamped with the code version that produced it.</p></div></div>
            </div>
          </div>
        </Section>

        <Section id="data" eyebrow="Evidence" title="Knowledge bases" intro={health && !health.offline && total ? `${total.toLocaleString()} records loaded on the backend right now.` : 'Record counts appear here when the backend is running.'}>
          <p className="mb-4 rounded-lg border border-line bg-well/60 px-4 py-3 text-[13.5px] leading-relaxed text-ink">
            Every question is answered from the <span className="font-semibold">real and synthetic records together</span> wherever
            a dataset has both (AFRB); FailureSensorIQ and the hydraulic rig hold real records only. Each evidence item keeps
            its REAL or SYNTHETIC label, and heavy reliance on synthetic support lowers confidence.
          </p>
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
          <Section id="results" eyebrow="Evaluation" title="Measured results" intro="From the project's benchmark of held-out cases, comparing the original pipeline with the current harness.">
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

        <Section id="stack" eyebrow="Implementation" title="How it is built">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[140px_minmax(0,1fr)] text-[14px]">
            {STACK.map(([k, v]) => <div key={k} className="contents"><dt className="font-semibold text-ink">{k}</dt><dd className="text-ink">{v}</dd></div>)}
          </dl>
        </Section>

        <Section id="use" eyebrow="Get started" title="Using it">
          <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {[
              ['Pick a dataset', 'Choose AFRB sensors, FailureSensorIQ or the hydraulic rig in the top bar. Real and synthetic records are used together automatically.'],
              ['Ask in Diagnostic chat', 'Give the readings you have, or start from an example. The answer, the agents’ reasoning and the evidence appear in the conversation.'],
              ['Review on the dashboard', 'The agent dashboard shows the latest diagnosis as the pipeline that produced it. Maximize any stage for the full detail.'],
              ['Inspect the trace', 'Open the Trace explorer to see how the agents agreed, step through every message, and download the trace for your team.'],
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
            <button type="button" className="btn-ghost border border-slate-300 px-5 py-2.5 text-[14px] text-ink" onClick={() => nav('/traces')}>Open the Trace explorer</button>
          </div>
        </Section>
      </div>
    </div>
  )
}
