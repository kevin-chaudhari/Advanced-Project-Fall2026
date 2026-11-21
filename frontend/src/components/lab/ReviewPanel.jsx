import { useEffect, useState } from 'react'
import { CheckCircle2, Loader2, PenLine, XCircle } from 'lucide-react'
import { cx } from '../ui'
import { addReview, getReviews } from '../../services/api'

/*
 * Human reviewer sign-off: approve, reject or change the diagnosis, with a required reason.
 * Each decision is stored against the trace (POST /reviews/{trace_id}) and listed with who and when.
 */

const DECISIONS = [
  ['approve', 'Approve', CheckCircle2, 'border-success-500 text-success-700'],
  ['reject', 'Reject', XCircle, 'border-danger-500 text-danger-700'],
  ['change', 'Change diagnosis', PenLine, 'border-warning-500 text-warning-700'],
]
const WHO_KEY = 'ida.reviewer.v1'
const readWho = () => { try { return localStorage.getItem(WHO_KEY) || '' } catch { return '' } }
const saveWho = (v) => { try { localStorage.setItem(WHO_KEY, v) } catch { /* storage unavailable */ } }

export default function ReviewPanel({ traceId, diagnosis, alternatives = [], experimentId = null, compact = false }) {
  const [items, setItems] = useState(null)
  const [decision, setDecision] = useState(null)
  const [reason, setReason] = useState('')
  const [label, setLabel] = useState('')
  const [who, setWho] = useState(readWho)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!traceId) return
    let live = true
    getReviews(traceId).then((r) => live && setItems(r.items)).catch(() => live && setItems([]))
    return () => { live = false }
  }, [traceId])

  if (!traceId) return null
  const latest = items?.[0]
  const submit = async () => {
    setBusy(true); setError(null)
    try {
      saveWho(who)
      const r = await addReview(traceId, { decision, reason, final_label: decision === 'change' ? label : null, reviewer: who, experiment_id: experimentId })
      setItems((x) => [r, ...(x || [])]); setDecision(null); setReason(''); setLabel('')
    } catch (e) { setError(e.response?.data?.detail || e.message) } finally { setBusy(false) }
  }

  return (
    <div className={cx('rounded-lg border border-line bg-surface', compact ? 'p-3' : 'p-4')}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[12.5px] font-semibold text-ink">Your review</p>
        {latest && (
          <span className="text-[12px] text-muted">
            Last: <b className="text-ink">{latest.decision === 'change' ? `changed to ${latest.final_label}` : `${latest.decision}d`}</b>
            {' '}by {latest.reviewer} · {new Date(latest.created_at).toLocaleString()}
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {DECISIONS.map(([d, l, Icon, tone]) => (
          <button key={d} type="button" onClick={() => setDecision(decision === d ? null : d)} aria-pressed={decision === d}
            className={cx('inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium focus-ring',
              decision === d ? `${tone} bg-white` : 'border-line text-ink hover:bg-well')}>
            <Icon size={13} />{l}
          </button>
        ))}
      </div>
      {decision && (
        <div className="mt-2 space-y-2">
          {decision === 'change' && (
            <label className="block text-[12px] text-muted">Correct diagnosis
              <input list="review-labels" value={label} onChange={(e) => setLabel(e.target.value)} className="input mt-1 py-1 text-[12.5px]" placeholder="e.g. Bearing Wear" />
              <datalist id="review-labels">{alternatives.filter((a) => a && a !== diagnosis).map((a) => <option key={a} value={a} />)}</datalist>
            </label>
          )}
          <label className="block text-[12px] text-muted">Reason (required — what did you check?)
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className="input mt-1 py-1 text-[12.5px]"
              placeholder={decision === 'approve' ? 'e.g. Matches vibration trend and last inspection' : 'e.g. Bearing noise heard on site; temperature normal on handheld'} />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input value={who} onChange={(e) => setWho(e.target.value)} placeholder="Your name" aria-label="Your name" className="input w-40 py-1 text-[12.5px]" />
            <button type="button" onClick={submit} disabled={busy || !reason.trim() || (decision === 'change' && !label.trim())} className="btn-primary py-1.5 text-[12.5px]">
              {busy && <Loader2 size={13} className="animate-spin" />}Save review
            </button>
            {error && <span className="text-[12px] text-danger-700">{error}</span>}
          </div>
        </div>
      )}
      {items?.length > 1 && (
        <details className="mt-2 text-[12px] text-muted">
          <summary className="cursor-pointer">Review history ({items.length})</summary>
          <ul className="mt-1 space-y-1">{items.map((r) => (
            <li key={r.review_id}><b className="text-ink">{r.decision}{r.final_label ? ` → ${r.final_label}` : ''}</b> by {r.reviewer}, {new Date(r.created_at).toLocaleString()}: {r.reason}</li>
          ))}</ul>
        </details>
      )}
    </div>
  )
}
