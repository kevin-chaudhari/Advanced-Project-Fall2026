import { useEffect, useRef } from 'react'
import { AGENT_COLOR, AGENT_SHORT } from '../../lib/agentColors'

/*
 * A small 3D picture of what Mission Control observes: the six agents of the council on a tilted
 * ring around the AgentTrace core, with the human operator above. Messages travel agent → agent
 * along the council mesh; each delivered message then travels agent → core, i.e. it is recorded.
 *
 * Plain canvas with a perspective projection — no 3D library. Drag to rotate. Pauses off-screen,
 * and draws one still frame when the user prefers reduced motion. Illustrative only: it shows how
 * the system works, not a live run.
 */

const KEYS = ['diagnostic_expert', 'pattern_agent', 'aggressive_agent', 'verification', 'ambiguity', 'human_review_coordinator']
const INK = '#17140F'
const MUTED = '#4A453D'
const LINE = '#C9B28E'      // primary-300
const CORE = '#6E5A3E'      // primary-700
const OPERATOR = '#78866B'  // success-500

function project(p, yaw, pitch, w, h) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
  const x1 = p.x * cy - p.z * sy
  const z1 = p.x * sy + p.z * cy
  const y2 = p.y * cp - z1 * sp
  const z2 = p.y * sp + z1 * cp
  const scale = Math.min(w * 0.36, h * 0.5)
  const dist = 3.2
  const f = dist / (dist + z2)
  return { x: w / 2 + x1 * f * scale, y: h * 0.58 + y2 * f * scale, f, z: z2 }
}

export default function Council3D({ className = '' }) {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let w = 0, h = 0, raf = 0, visible = true, last = performance.now()
    let yaw = 0.6, pitch = 0.42, drag = null, idleAt = 0

    // geometry: agents on a ring (y = 0), core at origin, operator above
    const nodes = KEYS.map((k, i) => {
      const a = (i / KEYS.length) * Math.PI * 2
      return { key: k, x: Math.cos(a), y: 0, z: Math.sin(a) }
    })
    const core = { x: 0, y: 0, z: 0 }
    const operator = { x: 0, y: -0.72, z: 0 }
    const pulses = []     // { from, to, t, kind: 'msg' | 'rec', color }
    let nextAt = 0

    const resize = () => {
      const r = canvas.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = r.width; h = r.height
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      if (reduced) draw()
    }

    const spawn = (now) => {
      const a = Math.floor(Math.random() * KEYS.length)
      let b = Math.floor(Math.random() * (KEYS.length - 1)); if (b >= a) b += 1
      pulses.push({ from: nodes[a], to: nodes[b], t: 0, kind: 'msg', color: AGENT_COLOR[KEYS[a]] })
      nextAt = now + 520 + Math.random() * 480
    }

    function line(p, q, color, width, dash) {
      ctx.beginPath()
      ctx.setLineDash(dash || [])
      ctx.strokeStyle = color; ctx.lineWidth = width
      ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke()
      ctx.setLineDash([])
    }

    function draw() {
      ctx.clearRect(0, 0, w, h)
      const P = nodes.map((n) => ({ n, ...project(n, yaw, pitch, w, h) }))
      const C = project(core, yaw, pitch, w, h)
      const O = project(operator, yaw, pitch, w, h)

      // orbit ring
      ctx.beginPath()
      for (let i = 0; i <= 72; i++) {
        const a = (i / 72) * Math.PI * 2
        const q = project({ x: Math.cos(a) * 1.0, y: 0, z: Math.sin(a) * 1.0 }, yaw, pitch, w, h)
        i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y)
      }
      ctx.strokeStyle = 'rgba(166,138,100,0.35)'; ctx.lineWidth = 1; ctx.stroke()

      // council mesh: every pair of agents can talk
      ctx.globalAlpha = 0.28
      for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) line(P[i], P[j], LINE, 0.8)
      ctx.globalAlpha = 1
      // trace spokes: every agent is recorded by the core
      for (const p of P) line(p, C, 'rgba(110,90,62,0.45)', 1, [3, 4])
      line(C, O, 'rgba(120,134,107,0.8)', 1.4, [5, 4])

      // pulses
      for (const s of pulses) {
        const a = project(s.from, yaw, pitch, w, h)
        const b = project(s.to, yaw, pitch, w, h)
        const x = a.x + (b.x - a.x) * s.t, y = a.y + (b.y - a.y) * s.t
        ctx.beginPath(); ctx.fillStyle = s.color
        ctx.globalAlpha = s.kind === 'rec' ? 0.75 : 1
        ctx.arc(x, y, s.kind === 'rec' ? 2.2 : 3.2, 0, Math.PI * 2); ctx.fill()
        ctx.globalAlpha = 1
      }

      // core (AgentTrace) and operator
      const coreR = 15 * C.f
      const g = ctx.createRadialGradient(C.x - coreR * 0.3, C.y - coreR * 0.3, 1, C.x, C.y, coreR)
      g.addColorStop(0, '#E0D0B5'); g.addColorStop(1, CORE)
      ctx.beginPath(); ctx.fillStyle = g; ctx.arc(C.x, C.y, coreR, 0, Math.PI * 2); ctx.fill()
      ctx.fillStyle = INK; ctx.font = '600 11.5px "IBM Plex Sans", system-ui, sans-serif'; ctx.textAlign = 'center'
      ctx.fillText('AgentTrace', C.x, C.y + coreR + 14)

      ctx.beginPath(); ctx.fillStyle = OPERATOR; ctx.arc(O.x, O.y, 9 * O.f, 0, Math.PI * 2); ctx.fill()
      ctx.fillStyle = MUTED; ctx.font = '500 11px "IBM Plex Sans", system-ui, sans-serif'
      ctx.fillText('Human operator', O.x, O.y - 14)

      // agents, far to near
      for (const p of [...P].sort((u, v) => v.z - u.z)) {
        const r = 11 * p.f
        const col = AGENT_COLOR[p.n.key]
        ctx.globalAlpha = 0.55 + 0.45 * Math.min(1, Math.max(0, (p.f - 0.7) / 0.6))
        ctx.beginPath(); ctx.fillStyle = col; ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.strokeStyle = '#FFFCF5'; ctx.lineWidth = 1.5; ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.stroke()
        ctx.fillStyle = INK; ctx.font = `${p.f > 1 ? 600 : 500} 11.5px "IBM Plex Sans", system-ui, sans-serif`
        ctx.fillText(AGENT_SHORT[p.n.key], p.x, p.y + r + 14)
        ctx.globalAlpha = 1
      }
    }

    function tick(now) {
      raf = requestAnimationFrame(tick)
      if (!visible) { last = now; return }
      const dt = Math.min(64, now - last); last = now
      if (!drag && now > idleAt) yaw += dt * 0.00018
      if (now > nextAt) spawn(now)
      for (const s of pulses) s.t += dt / (s.kind === 'msg' ? 1100 : 700)
      for (let i = pulses.length - 1; i >= 0; i--) {
        const s = pulses[i]
        if (s.t >= 1) {
          pulses.splice(i, 1)
          if (s.kind === 'msg') pulses.push({ from: s.to, to: core, t: 0, kind: 'rec', color: CORE })   // delivered → recorded
        }
      }
      draw()
    }

    const ro = new ResizeObserver(resize); ro.observe(canvas)
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting }); io.observe(canvas)
    const down = (e) => { drag = { x: e.clientX, y: e.clientY, yaw, pitch }; canvas.setPointerCapture?.(e.pointerId) }
    const move = (e) => {
      if (!drag) return
      yaw = drag.yaw + (e.clientX - drag.x) * 0.008
      pitch = Math.max(0.1, Math.min(1.1, drag.pitch - (e.clientY - drag.y) * 0.006))
      if (reduced) draw()
    }
    const up = () => { drag = null; idleAt = performance.now() + 1500 }
    canvas.addEventListener('pointerdown', down)
    canvas.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)

    resize()
    if (reduced) {
      pulses.push({ from: nodes[0], to: nodes[3], t: 0.55, kind: 'msg', color: AGENT_COLOR[KEYS[0]] })
      draw()
    } else raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); io.disconnect()
      canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [])

  return (
    <canvas ref={ref} className={`block w-full h-full cursor-grab active:cursor-grabbing touch-pan-y ${className}`}
      role="img" aria-label="Three-dimensional illustration: the six agents on a ring exchange messages; every delivered message is recorded by the AgentTrace core, which the human operator observes." />
  )
}
