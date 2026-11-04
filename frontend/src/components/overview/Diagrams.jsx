import { AGENT_COLOR, AGENT_SHORT } from '../../lib/agentColors'

/*
 * Explanatory diagrams for the overview page. They describe how the system is built and how a run
 * flows; they are not live data. Colours come from the existing palette and agent colours only.
 */

const C = {
  ink: '#17140F', muted: '#4A453D', line: '#E5DED1', surface: '#FFFCF5', well: '#EFE9DD',
  bronze: '#A68A64', bronzeDark: '#6E5A3E', bronzeSoft: '#F7F1E7', sage: '#6E8582', olive: '#78866B',
  oliveSoft: '#F0F2EB', clay: '#C18D4D', claySoft: '#FBF3E8',
}
const KEYS = ['diagnostic_expert', 'pattern_agent', 'aggressive_agent', 'verification', 'ambiguity', 'human_review_coordinator']

/* ── 1. architecture ──────────────────────────────────────────────────────── */

function Box({ x, y, w, h, title, lines = [], fill = C.surface, stroke = C.line, dashed, titleColor = C.ink }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="10" fill={fill} stroke={stroke} strokeWidth="1.2" strokeDasharray={dashed ? '5 4' : undefined} />
      <text x={x + 14} y={y + 24} fontSize="13.5" fontWeight="600" fill={titleColor}>{title}</text>
      {lines.map((l, i) => <text key={i} x={x + 14} y={y + 44 + i * 17} fontSize="11.5" fill={C.muted}>{l}</text>)}
    </g>
  )
}

function Arrow({ d, label, lx, ly, dashed, color = C.bronze, both }) {
  return (
    <g>
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '5 4' : undefined}
        markerEnd="url(#mc-arrow)" markerStart={both ? 'url(#mc-arrow-start)' : undefined} />
      {label && <text x={lx} y={ly} fontSize="11" fill={C.muted} textAnchor="middle">{label}</text>}
    </g>
  )
}

const ARCH_LABEL = { diagnostic_expert: 'Expert', pattern_agent: 'Pattern', aggressive_agent: 'Triage', verification: 'Verify', ambiguity: 'Ambiguity', human_review_coordinator: 'Coordinator' }

export function ArchitectureDiagram() {
  const rows = [
    ['Query preparation & retrieval', 'readings and missing channels · four-way search + rerank → EV-001 …'],
    ['Collaborative council', ''],
    ['Verification & feedback loop', 'claims checked against evidence · targeted retrieval · re-sync'],
    ['Uncertainty & escalation council', 'factor-based confidence · hard cases deliberate again'],
    ['Synthesis, claim validation, review gate', 'unsupported numbers removed · 8 criteria → auto-resolve or human review'],
  ]
  return (
    <div className="overflow-x-auto">
      <svg viewBox="0 0 1040 430" className="min-w-[760px] w-full h-auto" role="img"
        aria-label="Architecture: the human operator uses the Mission Control interface, which calls the FastAPI backend. The backend runs the orchestration harness (retrieval, the six-agent council, verification, uncertainty, synthesis and the review gate) over a knowledge base of real and synthetic records. The AgentTrace recorder observes every step and writes an append-only SQLite trace store, which the Trace explorer and exports read.">
        <defs>
          <marker id="mc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill={C.bronze} /></marker>
          <marker id="mc-arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill={C.bronze} /></marker>
        </defs>

        <Box x={16} y={150} w={142} h={92} title="Human operator" lines={['asks, reviews,', 'approves, audits']} fill={C.oliveSoft} stroke={C.olive} />
        <Box x={190} y={56} w={164} h={280} title="Mission Control UI" lines={['Overview', 'Agent dashboard', 'Diagnostic chat', 'Trace explorer', 'Data & evaluation', '', 'downloads: JSON,', 'transcript, CSV, zip']} />
        <Box x={386} y={120} w={146} h={150} title="FastAPI backend" lines={['POST /query', 'GET /traces …', 'GET /traces/{id}/', '      export', 'GET /health']} />

        {/* harness */}
        <rect x={562} y={16} width={462} height={300} rx="12" fill={C.bronzeSoft} stroke={C.bronze} strokeWidth="1.2" />
        <text x={578} y={40} fontSize="13.5" fontWeight="600" fill={C.bronzeDark}>Orchestration harness (the system under observation)</text>
        {rows.map(([t, d], i) => (
          <g key={t}>
            <rect x={578} y={54 + i * 51} width={430} height={44} rx="8" fill={C.surface} stroke={C.line} />
            <text x={592} y={72 + i * 51} fontSize="12.5" fontWeight="600" fill={C.ink}>{t}</text>
            {d && <text x={592} y={89 + i * 51} fontSize="11" fill={C.muted}>{d}</text>}
            {i === 1 && KEYS.map((k, j) => (
              <g key={k}>
                <circle cx={598 + j * 69} cy={90 + i * 51 - 2} r="5" fill={AGENT_COLOR[k]} />
                <text x={606 + j * 69} y={92 + i * 51 - 2} fontSize="10" fill={C.muted}>{ARCH_LABEL[k]}</text>
              </g>
            ))}
          </g>
        ))}

        <Box x={562} y={350} w={220} h={66} title="AgentTrace recorder" lines={['events · messages · reads · model', 'calls · evidence · score changes']} stroke={C.bronzeDark} dashed titleColor={C.bronzeDark} />
        <Box x={804} y={350} w={220} h={66} title="Knowledge base" lines={['REAL + SYNTHETIC records, labelled', 'FAISS · numeric · metadata search']} fill={C.claySoft} stroke={C.clay} />
        <Box x={386} y={350} w={146} h={66} title="Trace store" lines={['SQLite, append-only,', 'survives restarts']} />

        <Arrow d="M158,196 L188,196" both />
        <Arrow d="M354,196 L384,196" both />
        <Arrow d="M532,196 L560,196" both />
        <Arrow d="M914,350 L914,318" label="retrieval" lx={950} ly={338} />
        <Arrow d="M672,318 L672,348" dashed color={C.bronzeDark} label="observes every step" lx={740} ly={338} />
        <Arrow d="M562,383 L534,383" />
        <Arrow d="M459,350 L459,272" label="read-only trace API" lx={459} ly={300} />
      </svg>
    </div>
  )
}

/* ── 2. lifecycle of one question ─────────────────────────────────────────── */

const LIFE = [
  { t: 'Query preparation', who: [], d: 'The question is parsed into equipment type and sensor readings. Channels that were not reported are marked missing; nothing is filled in.', rec: 'QUERY_PREPARED' },
  { t: 'Evidence retrieval', who: [], d: 'Four searches (meaning, metadata, numeric similarity, historical outcomes) over real and synthetic records together, then a rerank. Each record becomes EV-001, EV-002 …; values the harness computes become D-001 …', rec: 'EVIDENCE_RETRIEVED, initial scoring' },
  { t: 'Private drafts', who: ['diagnostic_expert', 'pattern_agent', 'aggressive_agent'], d: 'Three agents analyse the same evidence in parallel, each with its own method, before seeing anyone else. These drafts keep real disagreement visible.', rec: 'one execution per agent, rendered prompt, model calls' },
  { t: 'Collaboration rounds', who: ['diagnostic_expert', 'pattern_agent', 'aggressive_agent', 'verification'], d: 'Agents share positions, answer questions, critique a peer whose view they cannot support, and update their beliefs from what they actually read. Up to three rounds, until they converge on a joint finding.', rec: 'every message, who read it, positions per round, council blend of the scores' },
  { t: 'Verification exchange', who: ['verification'], d: 'The Verification Analyst checks every claim against the cited evidence and replies to each agent that asked. Agreement between agents never counts as evidence.', rec: 'CLAIM_VALIDATED, verification requests and results' },
  { t: 'Targeted retrieval and re-sync', who: ['diagnostic_expert', 'pattern_agent'], d: 'Only when evidence is weak or two faults are too close: more targeted records are fetched, only the agent that needs them re-runs, and the council re-syncs for up to two rounds.', rec: 'FEEDBACK_LOOP_TRIGGERED, re-score, re-executions', optional: true },
  { t: 'Uncertainty', who: ['ambiguity'], d: 'Confidence is computed from visible factors: evidence quality, separation from the runner-up, completeness, contradictions, retrieval quality, agreement, reliance on synthetic data.', rec: 'confidence breakdown, uncertainty flags' },
  { t: 'Escalation council', who: KEYS, d: 'Hard cases only: all six agents deliberate again, challenge each other on the contested pair, and every challenge ends resolved or explicitly unresolved.', rec: 'COUNCIL_ROUND_*, challenges and outcomes', optional: true },
  { t: 'Synthesis and the review gate', who: ['human_review_coordinator'], d: 'The Coordinator writes the final answer from the board, numbers that cannot be traced are removed, and eight criteria decide AUTO_RESOLVE or REQUIRES_HUMAN_REVIEW.', rec: 'FINAL_SYNTHESIS_GENERATED, REVIEW_GATE_PASSED / HUMAN_REVIEW_TRIGGERED' },
]

export function LifecycleDiagram() {
  return (
    <ol className="relative">
      {LIFE.map((s, i) => (
        <li key={s.t} className="relative grid grid-cols-[36px_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
          {i < LIFE.length - 1 && <span className="absolute left-[17px] top-8 bottom-0 w-px bg-primary-200" aria-hidden />}
          <span className={`relative z-[1] grid h-9 w-9 place-items-center rounded-full border text-[12.5px] font-semibold tabular-nums ${s.optional ? 'border-dashed border-warning-500 bg-warning-50 text-warning-700' : 'border-primary-300 bg-primary-50 text-primary-700'}`}>{i + 1}</span>
          <div className="card p-4 min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="text-[15px] font-semibold text-ink">{s.t}</h3>
              {s.optional && <span className="chip border-warning-100 bg-warning-50 text-warning-700">only when needed</span>}
              <span className="ml-auto flex gap-1" aria-label={s.who.length ? `Agents: ${s.who.map((k) => AGENT_SHORT[k]).join(', ')}` : 'Harness step'}>
                {s.who.length
                  ? s.who.map((k) => <span key={k} title={AGENT_SHORT[k]} className="h-2.5 w-2.5 rounded-full" style={{ background: AGENT_COLOR[k] }} />)
                  : <span className="text-[11.5px] text-muted">harness</span>}
              </span>
            </div>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink">{s.d}</p>
            <p className="mt-2 text-[12px] text-muted"><span className="font-medium text-primary-700">Recorded:</span> {s.rec}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}

/* ── 3. how one agent updates its belief ──────────────────────────────────── */

// worked illustration of the pooling rule used by the council: own^(1−α) · Π peer^(α/n), normalised
const CANDS = ['Bearing wear', 'Seal failure', 'Cavitation']
const OWN = [0.6, 0.3, 0.1]
const PEERS = [[0.3, 0.6, 0.1], [0.45, 0.45, 0.1]]
function pool(alpha) {
  const raw = OWN.map((o, i) => Math.pow(o, 1 - alpha) * PEERS.reduce((m, p) => m * Math.pow(p[i], alpha / PEERS.length), 1))
  const s = raw.reduce((a, b) => a + b, 0)
  return raw.map((v) => v / s)
}

function Bars({ title, values, color, x, y }) {
  return (
    <g>
      <text x={x} y={y} fontSize="12" fontWeight="600" fill={C.ink}>{title}</text>
      {values.map((v, i) => (
        <g key={i}>
          <text x={x} y={y + 24 + i * 26} fontSize="11" fill={C.muted}>{CANDS[i]}</text>
          <rect x={x} y={y + 29 + i * 26} width="120" height="6" rx="3" fill={C.well} />
          <rect x={x} y={y + 29 + i * 26} width={120 * v} height="6" rx="3" fill={color} />
          <text x={x + 128} y={y + 35 + i * 26} fontSize="10.5" fill={C.muted}>{v.toFixed(2)}</text>
        </g>
      ))}
    </g>
  )
}

export function PoolingDiagram() {
  const alpha = 0.35
  const out = pool(alpha)
  const peerMean = CANDS.map((_, i) => PEERS.reduce((a, p) => a + p[i], 0) / PEERS.length)
  return (
    <div className="overflow-x-auto">
      <svg viewBox="0 0 690 220" className="min-w-[580px] w-full h-auto" role="img"
        aria-label={`Illustration of one belief update with openness 0.35: own view ${OWN.join(', ')}, two peers, updated view ${out.map((v) => v.toFixed(2)).join(', ')}.`}>
        <defs><marker id="mc-arrow-2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill={C.bronze} /></marker></defs>
        <rect x="8" y="10" width="190" height="120" rx="10" fill={C.surface} stroke={C.line} />
        <Bars title="Own evidence view" values={OWN} color={AGENT_COLOR.pattern_agent} x={22} y={32} />
        <rect x="8" y="140" width="190" height="66" rx="10" fill={C.surface} stroke={C.line} />
        <text x="22" y="162" fontSize="12" fontWeight="600" fill={C.ink}>Peers' positions it read</text>
        <text x="22" y="180" fontSize="11" fill={C.muted}>2 peers, average</text>
        <text x="22" y="196" fontSize="11" fill={C.muted}>{peerMean.map((v) => v.toFixed(2)).join(' · ')}</text>

        <path d="M200,70 C240,70 240,104 276,104" fill="none" stroke={C.bronze} strokeWidth="1.5" markerEnd="url(#mc-arrow-2)" />
        <path d="M200,172 C240,172 240,116 276,116" fill="none" stroke={C.bronze} strokeWidth="1.5" markerEnd="url(#mc-arrow-2)" />
        <text x="238" y="62" fontSize="11" fill={C.muted} textAnchor="middle">weight 1 − α</text>
        <text x="238" y="190" fontSize="11" fill={C.muted} textAnchor="middle">weight α</text>

        <rect x="280" y="70" width="140" height="80" rx="10" fill={C.bronzeSoft} stroke={C.bronze} />
        <text x="350" y="96" fontSize="12" fontWeight="600" fill={C.bronzeDark} textAnchor="middle">log-linear pool</text>
        <text x="350" y="116" fontSize="11" fill={C.ink} textAnchor="middle">own^(1−α) · Π peer^(α/n)</text>
        <text x="350" y="134" fontSize="11" fill={C.muted} textAnchor="middle">α = {alpha} (openness)</text>

        <path d="M420,110 L456,110" fill="none" stroke={C.bronze} strokeWidth="1.5" markerEnd="url(#mc-arrow-2)" />
        <rect x="460" y="10" width="222" height="196" rx="10" fill={C.surface} stroke={C.line} />
        <Bars title="Updated position" values={out} color={AGENT_COLOR.pattern_agent} x={474} y={32} />
        <text x="474" y="150" fontSize="11" fill={C.muted}>posted as a POSITION_UPDATE</text>
        <text x="474" y="166" fontSize="11" fill={C.muted}>with before → after; switching to</text>
        <text x="474" y="182" fontSize="11" fill={C.muted}>a challenger's label = concession</text>
      </svg>
    </div>
  )
}

export const OPENNESS = [
  { key: 'diagnostic_expert', a: 0.5, why: 'the integrator: listens most, keeps half its own evidence view' },
  { key: 'pattern_agent', a: 0.35, why: 'moves only when other evidence is strong' },
  { key: 'aggressive_agent', a: 0.25, why: 'safety first; 0 when a sensor safety rule fires' },
  { key: 'verification', a: 0.2, why: 'evidence first: agreement barely moves her' },
]

/* ── 4. the exposure ladder ───────────────────────────────────────────────── */

const LADDER = [
  ['RETRIEVED', 'The record was found by retrieval and entered the shared state.'],
  ['IN AGENT INPUT', "It was part of the state given to an agent's execution."],
  ['IN RENDERED PROMPT', 'It appears in the exact text sent to the model. TRUE or FALSE only when the full prompt was captured; otherwise UNKNOWN.'],
  ['CITED', 'An agent referred to it by ID in a claim or message.'],
  ['VERIFIED', 'The Verification Analyst checked the claim against it and recorded the result.'],
]

export function ExposureLadder() {
  return (
    <ol className="grid gap-2 sm:grid-cols-5 sm:items-end" aria-label="Evidence exposure ladder">
      {LADDER.map(([t, d], i) => (
        <li key={t} className="card p-3.5 flex flex-col" style={{ minHeight: `${150 + i * 26}px`, boxShadow: `inset 0 ${3 + i}px 0 #A68A64` }}>
          <span className="text-[11px] font-semibold tabular-nums text-primary-700">Level {i + 1}</span>
          <span className="mt-1 text-[13px] font-semibold text-ink">{t}</span>
          <span className="mt-1.5 text-[12.5px] leading-snug text-ink">{d}</span>
        </li>
      ))}
    </ol>
  )
}

const MSG = [
  ['SENT', 'posted to the board with sender, recipients, type, evidence IDs and the position it states'],
  ['RECEIVED', 'only when the recipient actually read it: an inbox read, a board read, or its text in a rendered prompt'],
  ['ANSWERED', 'a reply, counter-argument, concession or hold that points back to it'],
  ['RESOLVED / UNRESOLVED', 'challenges end one way or the other; open ones are never hidden'],
]

export function MessageLifecycle() {
  return (
    <ol className="flex flex-col sm:flex-row gap-2 sm:items-stretch" aria-label="Message lifecycle">
      {MSG.map(([t, d], i) => (
        <li key={t} className="flex sm:flex-1 items-stretch gap-2">
          <div className="card p-3 flex-1">
            <div className="text-[12.5px] font-semibold text-ink">{t}</div>
            <p className="mt-1 text-[12px] leading-snug text-muted">{d}</p>
          </div>
          {i < MSG.length - 1 && <span className="hidden sm:grid place-items-center text-primary-500" aria-hidden>→</span>}
        </li>
      ))}
    </ol>
  )
}
