/*
 * Shared vocabulary for the Trace Explorer. Message types are grouped into five families
 * so the graph, timeline and inspector use one colour language:
 *   statement  – what an agent asserts       (finding, position update, synthesis)
 *   ask        – what an agent requests      (question, evidence / verification / human request)
 *   answer     – replies grounded in evidence (evidence share, verification result, response, hold, concession)
 *   dispute    – disagreement                (challenge, counter-argument)
 *   flag       – risk and uncertainty         (risk flag, uncertainty flag)
 */
export const FAMILY = {
  statement: { label: 'Statement', stroke: '#4F4A42', chip: 'border-slate-300 bg-slate-50 text-slate-700' },
  ask: { label: 'Request', stroke: '#8C7250', chip: 'border-primary-200 bg-primary-50 text-primary-700' },
  answer: { label: 'Answer', stroke: '#5C726F', chip: 'border-secondary-100 bg-secondary-50 text-secondary-700' },
  dispute: { label: 'Dispute', stroke: '#A9594E', chip: 'border-danger-100 bg-danger-50 text-danger-700' },
  flag: { label: 'Flag', stroke: '#A9773A', chip: 'border-warning-100 bg-warning-50 text-warning-700' },
}

export const MSG = {
  FINDING: { family: 'statement', verb: 'shares a finding' },
  POSITION_UPDATE: { family: 'statement', verb: 'updates position' },
  SYNTHESIS: { family: 'statement', verb: 'synthesises' },
  QUESTION: { family: 'ask', verb: 'asks' },
  EVIDENCE_REQUEST: { family: 'ask', verb: 'requests evidence' },
  VERIFICATION_REQUEST: { family: 'ask', verb: 'requests verification' },
  HUMAN_INPUT_REQUEST: { family: 'ask', verb: 'needs a person' },
  EVIDENCE_SHARE: { family: 'answer', verb: 'shares evidence' },
  VERIFICATION_RESULT: { family: 'answer', verb: 'reports verification' },
  RESPONSE: { family: 'answer', verb: 'responds' },
  HOLD: { family: 'answer', verb: 'holds position' },
  CONCESSION: { family: 'answer', verb: 'concedes' },
  CHALLENGE: { family: 'dispute', verb: 'challenges' },
  COUNTER_ARGUMENT: { family: 'dispute', verb: 'counter-argues' },
  RISK_FLAG: { family: 'flag', verb: 'flags risk' },
  UNCERTAINTY_FLAG: { family: 'flag', verb: 'flags uncertainty' },
}
export const familyOf = (type) => MSG[type]?.family || 'statement'
export const typeLabel = (type) => String(type || '').toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Dominant family of an edge: any dispute wins (it is what reviewers look for), else the most frequent. */
export function edgeFamily(types) {
  const counts = {}
  for (const [t, n] of Object.entries(types || {})) counts[familyOf(t)] = (counts[familyOf(t)] || 0) + n
  if (counts.dispute) return 'dispute'
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'statement'
}

export const RESOLUTION = {
  RESOLVED: { label: 'Resolved', cls: 'text-success-700' },
  UNRESOLVED: { label: 'Unresolved', cls: 'text-danger-700' },
  PENDING: { label: 'Pending', cls: 'text-warning-700' },
  AWAITING_HUMAN: { label: 'Awaiting a person', cls: 'text-warning-700' },
}

export const HYP_STATUS = {
  PROPOSED: 'border-slate-300 bg-slate-50 text-slate-700',
  RETAINED: 'border-secondary-100 bg-secondary-50 text-secondary-700',
  CHALLENGED: 'border-danger-100 bg-danger-50 text-danger-700',
  QUALIFIED: 'border-warning-100 bg-warning-50 text-warning-700',
  MODIFIED: 'border-primary-200 bg-primary-50 text-primary-700',
  REJECTED: 'border-slate-200 bg-well text-muted line-through',
  UNRESOLVED: 'border-danger-100 bg-white text-danger-700',
  FINAL: 'border-success-100 bg-success-50 text-success-700',
}

export const SEGMENT_HINT = {
  collaboration: 'Agents share positions, question and challenge each other, then revise by reading the board',
  resync: 'New evidence arrived from targeted retrieval; the agents re-align from where they left off',
  verification: 'Each agent asks Verification to check the claims behind its finding',
  uncertainty: 'Ambiguity Detection reports what is still uncertain',
  council: 'Escalation council on a hard case',
  synthesis: 'The coordinator reads its inbox and states what the decision rests on',
}

export const fmtMs = (ms) => (ms == null ? '—' : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`)
export const fmtClock = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
