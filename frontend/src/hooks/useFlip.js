import { useCallback, useLayoutEffect, useRef } from 'react'

/**
 * Dependency-free FLIP layout animation (First, Last, Invert, Play).
 *
 *   const flip = useFlip([dep])
 *   <div ref={flip.register('panel-a')} />
 *   onClick={() => { flip.snapshot(); setState(...) }}
 *
 * `snapshot()` records every registered element's position before a layout
 * change; after React commits, each element that moved or resized is animated
 * from its old box to its new one with the Web Animations API. Elements that
 * share an id across two places (compact card → expanded panel) morph between
 * them. Respects prefers-reduced-motion.
 */
export default function useFlip(deps, { duration = 360, easing = 'cubic-bezier(0.2, 0.8, 0.2, 1)' } = {}) {
  const nodes = useRef(new Map())
  const before = useRef(null)

  const register = useCallback((id) => (el) => {
    if (el) nodes.current.set(id, el)
    else nodes.current.delete(id)
  }, [])

  const snapshot = useCallback(() => {
    const rects = new Map()
    nodes.current.forEach((el, id) => rects.set(id, el.getBoundingClientRect()))
    before.current = rects
  }, [])

  useLayoutEffect(() => {
    const prev = before.current
    before.current = null
    if (!prev) return
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) return
    nodes.current.forEach((el, id) => {
      const first = prev.get(id)
      if (!first || !el.animate) {
        el.animate?.([{ opacity: 0, transform: 'scale(0.98)' }, { opacity: 1, transform: 'none' }],
          { duration: duration * 0.8, easing })
        return
      }
      const last = el.getBoundingClientRect()
      const dx = first.left - last.left
      const dy = first.top - last.top
      const sameSize = Math.abs(first.width - last.width) < last.width * 0.05 + 2 &&
        Math.abs(first.height - last.height) < last.height * 0.05 + 2
      if (sameSize) {
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return
        el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration, easing })
        return
      }
      const inset = [first.top - last.top, last.right - first.right, last.bottom - first.bottom, first.left - last.left]
      if (inset.every((v) => v >= -2)) {
        // grow: reveal from the old box (no text distortion)
        const [t, r, b, l] = inset.map((v) => Math.max(0, v))
        el.animate(
          [{ clipPath: `inset(${t}px ${r}px ${b}px ${l}px round 12px)` }, { clipPath: 'inset(0px 0px 0px 0px round 12px)' }],
          { duration, easing },
        )
      } else {
        // shrink / move: slide from the old position and fade in
        el.animate([{ transform: `translate(${dx}px, ${dy}px)`, opacity: 0.4 }, { transform: 'none', opacity: 1 }],
          { duration, easing })
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { register, snapshot }
}
