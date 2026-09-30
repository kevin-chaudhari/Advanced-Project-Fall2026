import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'

const COLOR_MAP = {
  indigo: {
    border:   'hover:border-blue-400/70',
    gradient: 'linear-gradient(135deg, rgba(91,127,255,0.18), rgba(124,77,255,0.10))',
    glowBorder: 'rgba(91,127,255,0.35)',
    iconBg:   'rgba(91,127,255,0.18)',
    iconColor: '#7c9fff',
    btnGradient: 'linear-gradient(135deg, #5b7fff, #7c4dff)',
    btnShadow: 'rgba(91,127,255,0.45)',
    tagBg:    'rgba(91,127,255,0.14)',
    tagBorder: 'rgba(91,127,255,0.35)',
    tagColor:  '#a5bfff',
  },
  emerald: {
    border:   'hover:border-emerald-400/70',
    gradient: 'linear-gradient(135deg, rgba(16,185,129,0.14), rgba(57,255,20,0.07))',
    glowBorder: 'rgba(52,211,153,0.35)',
    iconBg:   'rgba(52,211,153,0.18)',
    iconColor: '#6ee7b7',
    btnGradient: 'linear-gradient(135deg, #10b981, #39ff14)',
    btnShadow: 'rgba(52,211,153,0.45)',
    tagBg:    'rgba(52,211,153,0.12)',
    tagBorder: 'rgba(52,211,153,0.30)',
    tagColor:  '#6ee7b7',
  },
}

export default function DatasetCard({ id, title, subtitle, description, icon: Icon, accentColor, tags, onSelect }) {
  const c = COLOR_MAP[accentColor] || COLOR_MAP.indigo

  return (
    <motion.div
      whileHover={{ scale: 1.03, y: -6 }}
      whileTap={{ scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 320, damping: 22 }}
      className={`glass-card p-8 cursor-pointer transition-all duration-300 group relative overflow-hidden ${c.border}`}
      style={{ borderColor: c.glowBorder }}
      onClick={() => onSelect(id)}
      role="button"
      tabIndex={0}
      id={`dataset-card-${id}`}
      aria-label={`Select ${title}`}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(id)}
    >
      {/* Gradient background on hover */}
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none rounded-[18px]"
        style={{ background: c.gradient }}
      />

      {/* Glow orb in top-right */}
      <div
        className="absolute -top-12 -right-12 w-36 h-36 rounded-full opacity-20 group-hover:opacity-40 transition-opacity duration-500 blur-2xl pointer-events-none"
        style={{ background: c.iconBg }}
      />

      {/* Icon */}
      <div
        className="w-14 h-14 rounded-2xl flex items-center justify-center mb-5 group-hover:scale-110 transition-transform relative z-10"
        style={{ background: c.iconBg, border: `1px solid ${c.tagBorder}` }}
      >
        <Icon size={28} style={{ color: c.iconColor }} />
      </div>

      <h3 className="text-xl font-extrabold text-white mb-1 relative z-10">{title}</h3>
      <p className="text-sm font-semibold mb-4 relative z-10" style={{ color: c.iconColor }}>{subtitle}</p>
      <p className="text-sm text-[var(--text-muted)] leading-relaxed mb-6 relative z-10">{description}</p>

      {/* Tags */}
      <div className="flex flex-wrap gap-2 mb-6 relative z-10">
        {tags.map((tag) => (
          <span
            key={tag}
            className="text-xs px-3 py-1 rounded-full font-medium"
            style={{ background: c.tagBg, border: `1px solid ${c.tagBorder}`, color: c.tagColor }}
          >
            {tag}
          </span>
        ))}
      </div>

      {/* CTA */}
      <button
        className="w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl text-white font-bold text-sm relative z-10 transition-all group-hover:shadow-lg"
        style={{
          background: c.btnGradient,
          boxShadow: `0 0 24px ${c.btnShadow}40`,
        }}
      >
        Select Dataset
        <ArrowRight size={16} className="group-hover:translate-x-1.5 transition-transform" />
      </button>
    </motion.div>
  )
}
