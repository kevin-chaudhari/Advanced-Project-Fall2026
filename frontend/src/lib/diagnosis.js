/*
 * Read-only view model over a /query response.
 * Every value comes from the backend payload; when a field is absent the view gets null,
 * never a placeholder number.
 */

const STATUS_RANK = { error: 4, warning: 3, loop: 2, ok: 1 }

export const AGENT_STATUS = {
  done: { label: 'Completed', tone: 'success' },
  rerun: { label: 'Re-run in feedback loop', tone: 'warning' },
  warning: { label: 'Completed with warnings', tone: 'warning' },
  failed: { label: 'Failed', tone: 'danger' },
  idle: { label: 'No activity recorded', tone: 'muted' },
}

/** Agents in the order the backend reports them, joined with their persona output and timeline events. */
export function buildAgents(result) {
  const h = result?.harness || {}
  const reports = h.agents || {}
  const outputs = result?.agent_outputs || []
  const timeline = h.timeline || []
  const evidence = h.evidence || []
  const keys = Object.keys(reports)
  const ordered = keys.length ? keys : outputs.map((_, i) => `agent_${i}`)

  return ordered.map((key, i) => {
    const report = reports[key] || null
    const out = outputs.find((o) => o.agent_name === report?.display_name) || outputs[i] || {}
    // analysis passes only: council messages and the review-gate verdict are not this agent's own status
    const events = timeline.filter((e) => e.agent === key && e.stage !== 'review_gate' && !/deliberate/.test(e.action || ''))
    const worst = events.reduce((w, e) => ((STATUS_RANK[e.status] || 0) > (STATUS_RANK[w] || 0) ? e.status : w), null)
    const status = !events.length ? 'idle' : worst === 'error' ? 'failed' : worst === 'warning' ? 'warning' : worst === 'loop' ? 'rerun' : 'done'
    const passes = events.filter((e) => /analyze/.test(e.action || '')).length
    const isCoordinator = key === 'human_review_coordinator' || out.execution_mode === 'synthesis'
    const summary = isCoordinator ? (report?.finding_label || out.diagnosis) : (report?.finding || out.diagnosis)
    const toItems = (arr) => (arr || []).map((s) => (typeof s === 'string' ? { statement: s, evidence_ids: [] } : s))
    return {
      key,
      name: report?.display_name || out.agent_name || key,
      persona: out.agent_persona || null,
      role: out.persona_title || null,
      purpose: out.persona_description || null,
      mode: out.execution_mode || null,
      status,
      passes,
      durationMs: events.reduce((s, e) => s + (e.duration_ms || 0), 0),
      summary: summary || null,
      label: report?.finding_label || null,
      confidence: report?.confidence ?? out.agent_confidence ?? null,
      narrative: report?.narrative || out.reasoning || null,
      recommendation: report?.recommendation || out.recommendation || null,
      supporting: toItems(report?.supporting_evidence),
      contradicting: toItems(report?.contradicting_evidence),
      missing: toItems(report?.missing_information),
      hypotheses: report?.hypotheses || [],
      evidenceIds: report?.evidence_ids?.length ? report.evidence_ids : evidence.filter((e) => e.used_by?.includes(key)).map((e) => e.evidence_id),
      claimsRemoved: report?.claims_removed ?? 0,
      engine: report?.mode || null,
    }
  })
}

/** Everything the dashboard and the chat need, derived once. */
export function summarize(result, run = {}) {
  if (!result) return null
  const h = result.harness || {}
  const review = h.review || {}
  const decision = result.review_decision || review.decision || h.review_decision || null
  const evidence = h.evidence || []
  const comp = h.evidence_composition || (evidence.length ? evidence.reduce((a, e) => ({ ...a, [e.source_type]: (a[e.source_type] || 0) + 1 }), {}) : null)
  const ts = (h.timeline || []).map((t) => t.timestamp).filter(Boolean)
  const cv = h.claim_validation || null
  const ver = h.verification || null
  const council = h.council || null
  const extraRounds = (h.retrieval?.rounds || []).filter((r) => r.round > 0)
  const deficiencies = (h.deficiencies_history || []).flat()
  const criteria = review.criteria || []

  return {
    label: h.predicted_label || null,
    answer: result.direct_answer || null,
    explanation: result.final_diagnosis || null,
    recommendation: result.recommendation || null,
    confidence: typeof result.confidence === 'number' ? result.confidence : null,
    decision,
    needsReview: decision === 'REQUIRES_HUMAN_REVIEW',
    reviewReasons: review.reasons || [],
    criteria,
    criteriaPassed: criteria.filter((c) => c.passed).length,
    // threshold read from the gate's own G1 description, e.g. "Confidence ≥ 0.65"
    reviewThreshold: (() => {
      const m = criteria.map((c) => /^confidence\s*≥\s*([\d.]+)/i.exec(c.description || '')).find(Boolean)
      return m ? Number(m[1]) : null
    })(),
    evidence,
    evidenceCount: evidence.length || result.retrieved_context_count || 0,
    provenance: comp,
    supportingStatements: result.supporting_evidence || [],
    reasoning: result.reasoning || [],
    ambiguity: h.ambiguity || null,
    confidenceFactors: h.confidence?.factors || [],
    verification: ver,
    claims: cv,
    council,
    feedbackRounds: h.feedback_rounds ?? 0,
    extraRetrieval: extraRounds,
    deficiencies,
    dataset: result.dataset_used || run.dataset || null,
    dataMode: result.data_mode || h.data_mode || run.mode || null,
    llmMode: h.llm_mode || null,
    latencyMs: h.latency_ms ?? null,
    analysedAt: ts.length ? Math.max(...ts) * 1000 : run.finishedAt || null,
    runId: h.run_id || null,
    agents: buildAgents(result),
  }
}

export const confidenceTone = (v) => (v == null ? 'muted' : v >= 0.65 ? 'success' : v >= 0.45 ? 'warning' : 'danger')

export function fmtTime(ms, withDate = false) {
  if (!ms) return null
  const d = new Date(ms)
  const sameDay = new Date().toDateString() === d.toDateString()
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return withDate || !sameDay ? `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${time}` : time
}

export const stripCites = (s) => String(s || '').replace(/\s*\[(?:EV|D)-\d{3,}(?:,\s*(?:EV|D)-\d{3,})*\]/g, '').trim()
