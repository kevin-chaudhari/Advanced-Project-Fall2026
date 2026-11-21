import { useState } from 'react'
import { cx } from '../ui'

/*
 * Interaction map for a two-sensor grid experiment: X = one sensor, Y = the other, one cell per
 * combination. Thick edges mark where the diagnosis changes between neighbouring cells; the
 * baseline cell is outlined. Colour by diagnosis, confidence, lead over runner-up or review decision.
 */

const fmt = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 })
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const shade = (t) => `rgba(110,90,62,${0.12 + 0.78 * Math.max(0, Math.min(1, t))})`

export default function GridChart({ grid, colorOf, onOpenRun }) {
  const [by, setBy] = useState('answer')
  if (!grid) return null
  const rows = [...grid.rows].map((r, j) => ({ r, y: grid.y_values[j] })).reverse()   // highest Y on top
  const margins = grid.rows.flat().filter((c) => c?.margin != null).map((c) => c.margin)
  const mMax = Math.max(0.2, ...margins)
  const fill = (c) => {
    if (!c) return '#F1ECE1'
    if (by === 'answer') return colorOf(c.answer)
    if (by === 'confidence') return shade(c.confidence ?? 0)
    if (by === 'margin') return shade((c.margin ?? 0) / mMax)
    return c.review_decision === 'AUTO_RESOLVE' ? '#78866B' : '#C18D4D'
  }
  const dark = (c) => by === 'answer' || by === 'review' || (by === 'confidence' && (c?.confidence ?? 0) > 0.55) || (by === 'margin' && (c?.margin ?? 0) / mMax > 0.55)
  const differs = (a, b) => a && b && a.answer !== b.answer
  const xu = grid.x_unit ? ` (${grid.x_unit})` : ''
  const yu = grid.y_unit ? ` (${grid.y_unit})` : ''

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 text-[12px]">
        <label className="inline-flex items-center gap-1.5 text-muted">Colour
          <select value={by} onChange={(e) => setBy(e.target.value)} className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px] text-ink">
            <option value="answer">by diagnosis</option><option value="confidence">by confidence</option>
            <option value="margin">by lead over runner-up</option><option value="review">by review decision</option>
          </select></label>
        <span className={cx('rounded-md border px-2 py-0.5 font-medium', grid.interacts ? 'border-warning-500 bg-warning-50 text-warning-700' : 'border-line text-muted')}>
          {grid.interacts ? 'Sensors interact' : 'No interaction found'}
        </span>
        <span className="text-muted">{grid.filled} of {grid.total} combinations · {grid.boundaries} diagnosis boundaries</span>
      </div>
      <p className="mt-1.5 text-[12.5px] text-ink">{grid.note}</p>

      <div className="mt-3 overflow-x-auto">
        <div className="inline-grid items-stretch gap-0" style={{ gridTemplateColumns: `auto repeat(${grid.x_values.length}, minmax(64px, 1fr))` }}>
          {rows.map(({ r, y }, j) => (
            <div key={y} className="contents">
              <span className="flex items-center justify-end pr-2 text-[11.5px] tabular-nums text-muted">{fmt(y)}</span>
              {r.map((c, i) => {
                const right = differs(c, r[i + 1])
                const below = differs(c, rows[j + 1]?.r[i])
                return (
                  <button key={i} type="button" disabled={!c} onClick={() => c && onOpenRun?.(c.run_index)}
                    title={c ? `${grid.x_label} ${fmt(grid.x_values[i])} · ${grid.y_label} ${fmt(y)} → ${c.answer}, ${pct(c.confidence)}, lead ${c.margin?.toFixed(2) ?? '—'}, ${c.review_decision === 'AUTO_RESOLVE' ? 'auto-resolve' : 'human review'}${c.is_baseline ? ' (baseline)' : ''}` : 'not run'}
                    className={cx('relative h-14 border border-surface text-left focus-ring', c?.is_baseline && 'z-10 outline outline-[3px] -outline-offset-[3px] outline-ink')}
                    style={{ background: fill(c), borderRightWidth: right ? 3 : 1, borderRightColor: right ? '#17140F' : undefined, borderBottomWidth: below ? 3 : 1, borderBottomColor: below ? '#17140F' : undefined }}>
                    {c && <span className={cx('absolute inset-x-1 bottom-0.5 truncate text-[10.5px] leading-tight', dark(c) ? 'text-surface' : 'text-ink')}>
                      {by === 'answer' ? c.answer : by === 'confidence' ? pct(c.confidence) : by === 'margin' ? (c.margin?.toFixed(2) ?? '—') : (c.review_decision === 'AUTO_RESOLVE' ? 'auto' : 'review')}
                    </span>}
                  </button>
                )
              })}
            </div>
          ))}
          <span />
          {grid.x_values.map((x) => <span key={x} className="pt-1 text-center text-[11.5px] tabular-nums text-muted">{fmt(x)}</span>)}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-6 text-[12px] text-ink">
        <span>→ {grid.x_label}{xu}</span><span>↑ {grid.y_label}{yu}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
        {by === 'answer' && grid.answers.map((a) => <span key={a} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: colorOf(a) }} />{a}</span>)}
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 outline outline-2 outline-ink" />baseline</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-1 bg-ink" />diagnosis changes across this edge</span>
        <span>Click a cell to compare that run with the baseline.</span>
      </div>
    </div>
  )
}
