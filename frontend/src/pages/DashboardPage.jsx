import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, AlertTriangle, MessageSquareText, MessageCircleQuestion } from 'lucide-react'
import { useDiagnostics, DATASETS } from '../state/DiagnosticsContext'
import { summarize, fmtTime } from '../lib/diagnosis'
import { ConfidenceIndicator, ReviewDecision } from '../components/primitives'
import FullscreenPanel from '../components/FullscreenPanel'
import { StageColumn, FlowArrowDown } from '../components/dashboard/StageColumn'
import { CouncilDetail } from '../components/diagnosis/details'
import {
  EvidenceBody, EvidenceFull, InitialBody, InitialFull, VerificationBody, VerificationFull,
  AmbiguityBody, AmbiguityFull, FinalBody, FinalFull, VerificationCompact, AmbiguityCompact, FinalCompact,
} from '../components/dashboard/columns'
import { SensorHealthChart, HypothesisComparisonChart } from '../components/DiagnosticCharts'
import { SensorPanel, HypothesisPanel } from '../components/ReportPanels'
import { lazy, Suspense } from 'react'

// the timeline is the Decision Explorer's own component; it loads on demand like the explorer does in chat
const ExplorerTimeline = lazy(() => import('../components/dashboard/ExplorerTimeline'))
import { agentColor } from '../lib/agentColors'

function StatusStrip({ lastRun, latest }) {
  const nav = useNavigate()
  if (!lastRun || lastRun === latest) return null
  if (!lastRun.result && !lastRun.error) {
    return (
      <div role="status" className="flex items-center gap-2.5 rounded-lg border border-primary-200 bg-primary-50 px-4 py-2.5 text-[13px] text-ink">
        <Loader2 size={15} className="animate-spin text-primary-700 shrink-0" aria-hidden />
        <span className="shrink-0 font-medium">Agents are analysing</span>
        <span className="truncate text-muted">{lastRun.question}</span>
        {latest && <span className="hidden md:inline ml-auto shrink-0 text-[12px] text-muted">Showing the previous result until it finishes</span>}
      </div>
    )
  }
  if (lastRun.error) {
    return (
      <div role="alert" className="flex items-center gap-2.5 rounded-lg border border-danger-100 bg-danger-50 px-4 py-2.5 text-[13px] text-danger-700">
        <AlertTriangle size={15} className="shrink-0" aria-hidden />
        <span className="min-w-0 truncate"><b className="font-semibold">The latest question failed:</b> {lastRun.error}</span>
        <button type="button" onClick={() => nav(`/chat#run-${lastRun.id}`)} className="ml-auto shrink-0 text-[12.5px] font-medium underline underline-offset-2 focus-ring rounded">Open in chat</button>
      </div>
    )
  }
  return null
}

function EmptyDashboard() {
  const nav = useNavigate()
  const { health, dataset, counts, loaded, running, lastRun } = useDiagnostics()
  const ds = DATASETS.find((d) => d.id === dataset)
  return (
    <div className="h-full grid place-items-center p-6">
      <div className="max-w-xl text-center">
        {running ? (
          <>
            <Loader2 size={22} className="mx-auto animate-spin text-primary-700" aria-hidden />
            <h1 className="mt-4 text-[22px] font-semibold tracking-[-0.01em]">The agents are working on your first question</h1>
            <p className="mt-2 text-[14px] text-muted line-clamp-2">{lastRun?.question}</p>
          </>
        ) : (
          <>
            <h1 className="text-[24px] font-semibold tracking-[-0.01em]">No diagnosis yet</h1>
            <p className="mt-2 text-[14px] leading-relaxed text-muted">
              Ask a question with the readings you have. When the six agents finish, their conclusion, confidence and
              review decision appear here.
            </p>
            <button type="button" className="btn-primary mt-5" onClick={() => nav('/chat')}>
              <MessageSquareText size={15} aria-hidden /> Ask a diagnostic question
            </button>
            <p className="mt-4 text-[12.5px] text-muted">
              {health?.offline ? 'The backend is not reachable. Start it, then recheck the connection in the top bar.'
                : !health ? 'Checking the backend…'
                  : loaded ? `${ds?.label}: ${Object.entries(counts).map(([k, n]) => `${n.toLocaleString()} ${k}`).join(', ')} records ready.`
                    : `${ds?.label} is not loaded on the backend yet.`}
            </p>
          </>
        )}
        {lastRun?.error && <p className="mt-4 text-[12.5px] text-danger-700">Last attempt failed: {lastRun.error}</p>}
      </div>
    </div>
  )
}

function QuestionBar({ run, s, fresh }) {
  const nav = useNavigate()
  const ds = DATASETS.find((d) => d.id === s.dataset)
  return (
    <section aria-label="Latest question" className="card shrink-0 flex flex-wrap lg:flex-nowrap items-center gap-x-5 gap-y-3 px-4 sm:px-5 py-3"
      style={{ background: '#F3EEE3' }}>
      <div className="flex items-center gap-2 shrink-0">
        <MessageCircleQuestion size={18} className="text-primary-700" aria-hidden />
        <span className="text-[13.5px] font-semibold text-ink whitespace-nowrap">User question</span>
      </div>
      <p className="min-w-0 flex-1 basis-[320px] text-[14.5px] font-medium leading-snug text-ink line-clamp-2" title={run.question}>{run.question}</p>
      <div className="flex items-center gap-4 shrink-0">
        <div className="hidden md:block text-right text-[12px] leading-tight text-muted">
          <div>{ds?.label}, {s.dataMode} data</div>
          <div>{s.analysedAt ? `Analysed ${fmtTime(s.analysedAt)}` : ''}{s.latencyMs != null ? ` · ${Math.round(s.latencyMs)} ms` : ''}</div>
        </div>
        <div className="w-[130px]"><ConfidenceIndicator value={s.confidence} threshold={s.reviewThreshold} /></div>
        <ReviewDecision decision={s.decision} animate={fresh} />
        <button type="button" onClick={() => nav(`/chat#run-${run.id}`)} className="btn-ghost border border-line px-2.5 py-1.5 text-[12.5px] whitespace-nowrap">Open in chat</button>
      </div>
    </section>
  )
}

const STAGES = [
  { id: 'evidence', n: 1, title: 'Retrieved evidence', subtitle: 'Records retrieved and what they point to', Body: EvidenceBody, Full: EvidenceFull, bodyProps: { compact: true } },
  { id: 'initial', n: 2, title: 'Initial agent analysis', subtitle: 'Three independent perspectives, run in parallel', Body: InitialBody, Full: InitialFull, bodyProps: { horizontal: true } },
  { id: 'verify', n: 3, title: 'Verification', subtitle: 'Cross-check against the evidence', Body: VerificationCompact, Full: VerificationFull, accent: agentColor('verification') },
  { id: 'ambig', n: 4, title: 'Ambiguity assessment', subtitle: 'Uncertainty and alternatives', Body: AmbiguityCompact, Full: AmbiguityFull, accent: agentColor('ambiguity') },
  { id: 'final', n: 5, title: 'Final recommendation', subtitle: 'Coordinated output and review gate', Body: FinalCompact, Full: FinalFull, accent: agentColor('human_review_coordinator') },
  { id: 'sensors', title: 'Sensor health overview', subtitle: 'Each reported channel against its normal band',
    Body: ({ result }) => <SensorHealthChart harness={result.harness} />,
    Full: ({ result }) => <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)]"><div className="card p-5 self-start"><SensorHealthChart harness={result.harness} /></div><div className="card p-5 min-w-0"><SensorPanel harness={result.harness} /></div></div> },
  { id: 'hyps', title: 'Fault hypothesis comparison', subtitle: 'Leading faults and the review-gate margin',
    Body: ({ result, s }) => <HypothesisComparisonChart harness={result.harness} decision={s.decision} />,
    Full: ({ result, s }) => <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)]"><div className="card p-5 self-start"><HypothesisComparisonChart harness={result.harness} decision={s.decision} /></div><div className="card p-5 min-w-0"><HypothesisPanel harness={result.harness} /></div></div> },
]
const stage = (id) => STAGES.find((st) => st.id === id)

/**
 * Agent Dashboard — the latest diagnosis laid out like the Decision Explorer, kept short:
 *   left:  1. retrieved evidence, sensor health chart, fault hypothesis comparison (short cards)
 *   right: 2. the three independent agents side by side
 *          ↓ 3. verification ↓ (agent council, when it ran) ↓ 4. ambiguity ↓ 5. final recommendation (compact rows)
 * then the Decision Explorer's interaction timeline. Every card can be maximized for the full detail.
 */
export default function DashboardPage() {
  const { latest, lastRun } = useDiagnostics()
  const s = useMemo(() => (latest ? summarize(latest.result, latest) : null), [latest])
  const [max, setMax] = useState(null)
  if (!latest) return <EmptyDashboard />
  const fresh = latest.finishedAt && Date.now() - latest.finishedAt < 8000
  const maxStage = stage(max)
  const props = { s, result: latest.result, runId: latest.id }
  const council = s.council?.convened ? s.council : null

  const block = (id, extra = {}) => {
    const st = stage(id)
    return (
      <StageColumn n={st.n} title={st.title} subtitle={st.subtitle} accent={st.accent} onMaximize={() => setMax(st.id)}
        className={extra.className} bodyClass={extra.bodyClass}>
        <st.Body {...props} {...st.bodyProps} />
      </StageColumn>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex flex-col gap-3 p-3 sm:p-4">
        <StatusStrip lastRun={lastRun} latest={latest} />
        <QuestionBar run={latest} s={s} fresh={fresh} />
        <div className="grid items-start gap-3 lg:grid-cols-[300px_minmax(0,1fr)] 2xl:grid-cols-[340px_minmax(0,1fr)]">
          {/* left: evidence and the two charts, each short (scrolls inside; maximize for all of it) */}
          <div className="min-w-0 flex flex-col gap-3">
            {block('evidence', { className: 'max-h-[300px]' })}
            {block('sensors', { className: 'max-h-[330px]', bodyClass: 'py-2.5' })}
            {block('hyps', { className: 'max-h-[340px]', bodyClass: 'py-2.5' })}
          </div>
          {/* right: the workflow, top to bottom */}
          <div className="min-w-0 flex flex-col">
            {block('initial', { className: 'bg-well/60' })}
            <FlowArrowDown />
            {block('verify', { bodyClass: 'py-2.5' })}
            {council && (
              <>
                <FlowArrowDown />
                <StageColumn title="Agent council" subtitle={`The agents deliberated · ${council.messages} messages over ${council.rounds} round(s)`}
                  onMaximize={() => setMax('ambig')} bodyClass="py-2.5">
                  <CouncilDetail s={s} />
                </StageColumn>
              </>
            )}
            <FlowArrowDown />
            {block('ambig', { bodyClass: 'py-2.5' })}
            <FlowArrowDown />
            {block('final', { bodyClass: 'py-2.5' })}
          </div>
        </div>
        <Suspense fallback={<div className="card p-4 text-[12.5px] text-muted">Loading timeline…</div>}>
          <ExplorerTimeline result={latest.result} question={latest.question} />
        </Suspense>
      </div>
      {maxStage && (
        <FullscreenPanel title={`${maxStage.n ? `${maxStage.n}. ` : ''}${maxStage.title}`} subtitle={latest.question} accent={maxStage.accent} onClose={() => setMax(null)}>
          <maxStage.Full {...props} />
        </FullscreenPanel>
      )}
    </div>
  )
}
