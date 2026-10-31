import { useEffect, useState } from 'react'
import { Disclosure } from '../primitives'
import { stripCites } from '../../lib/diagnosis'
import {
  VerificationDetail, verificationMeta, FeedbackDetail, feedbackMeta, CouncilDetail, councilMeta, GateDetail,
} from '../diagnosis/details'

/** Secondary pipeline details, in the order they happened. All collapsed by default. */
export default function DiagnosticTimeline({ s, runId }) {
  const [open, setOpen] = useState(null)
  useEffect(() => { setOpen(null) }, [runId])
  const items = [
    { id: 'verify', title: 'Verification', meta: verificationMeta(s), body: <VerificationDetail s={s} /> },
    { id: 'feedback', title: 'Targeted retrieval', meta: feedbackMeta(s), body: <FeedbackDetail s={s} /> },
    s.council && { id: 'council', title: 'Agent council', meta: councilMeta(s), body: <CouncilDetail s={s} /> },
    {
      id: 'coord', title: 'Coordinator decision', meta: s.decision === 'AUTO_RESOLVE' ? 'Auto-resolve' : s.decision ? 'Escalated' : '—',
      body: (
        <div className="space-y-1.5 text-[12.5px] text-ink/85">
          {s.answer && <p>{s.answer}</p>}
          {s.recommendation && <p className="text-muted"><span className="text-ink font-medium">Recommended:</span> {stripCites(s.recommendation)}</p>}
          {s.llmMode && <p className="text-[11.5px] text-muted">Engine: {s.llmMode}</p>}
        </div>
      ),
    },
    { id: 'gate', title: 'Human-review gate', meta: s.criteria.length ? `${s.criteriaPassed}/${s.criteria.length} passed` : '—', body: <GateDetail s={s} /> },
  ].filter(Boolean)

  return (
    <section aria-labelledby="trail-title" className="card flex flex-col shrink-0">
      <header className="px-5 pt-4 pb-2">
        <h2 id="trail-title" className="section-title">Decision trail</h2>
      </header>
      <ol className="px-3 pb-3">
        {items.map((it, i) => (
          <li key={it.id} className="relative">
            {/* rail connecting the steps: the trail is a real sequence */}
            {i < items.length - 1 && <span className="absolute left-[19px] top-7 bottom-0 w-px bg-line" aria-hidden />}
            <Disclosure
              open={open === it.id} onToggle={(o) => setOpen(o ? it.id : null)}
              headerClass="px-2 py-2 hover:bg-well/60"
              title={<span className="text-[13px] font-medium text-ink">{it.title}</span>}
              meta={it.meta}
              bodyClass="ml-7 mr-2 mb-2 rounded-lg bg-well/50 p-3">
              {it.body}
            </Disclosure>
          </li>
        ))}
      </ol>
    </section>
  )
}
