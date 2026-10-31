import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Minimize2 } from 'lucide-react'

/**
 * Maximised view that covers the whole browser window (not just the panel's grid cell).
 * Esc or Minimize closes it; focus is trapped inside and restored afterwards; page scroll is locked.
 */
export default function FullscreenPanel({ title, subtitle, accent, onClose, children }) {
  const titleId = useId()
  const panel = useRef(null)
  const closeBtn = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const before = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeBtn.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onCloseRef.current() }
      if (e.key !== 'Tab' || !panel.current) return
      const f = panel.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (!f.length) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      before?.focus?.({ preventScroll: true })
    }
  }, [])

  return createPortal(
    <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId}
      className="fixed inset-0 z-50 flex flex-col bg-canvas de-fade">
      <header className="shrink-0 flex items-center gap-3 border-b border-line bg-surface px-4 sm:px-8 py-3"
        style={accent ? { boxShadow: `inset 0 3px 0 ${accent}` } : undefined}>
        <div className="min-w-0">
          <h2 id={titleId} className="text-[16px] font-semibold text-ink truncate">{title}</h2>
          {subtitle && <p className="text-[12.5px] text-muted truncate">{subtitle}</p>}
        </div>
        <button ref={closeBtn} type="button" onClick={onClose} className="btn-ghost ml-auto border border-line px-3 py-1.5 text-[13px]" title="Minimize (Esc)">
          <Minimize2 size={14} aria-hidden /> Minimize
        </button>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="px-4 sm:px-8 py-6 de-fade-up">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
