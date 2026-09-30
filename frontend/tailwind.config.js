/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F7F9FC',
        surface: '#FFFFFF',
        ink: '#0F172A',
        muted: '#64748B',
        line: '#E2E8F0',
        primary: { 50: '#EFF6FF', 100: '#DBEAFE', 200: '#BFDBFE', 500: '#3B82F6', 600: '#2563EB', 700: '#1D4ED8' },
        secondary: { 50: '#ECFEFF', 100: '#CFFAFE', 500: '#06B6D4', 600: '#0891B2', 700: '#0E7490' },
        success: { 50: '#F0FDF4', 100: '#DCFCE7', 600: '#16A34A', 700: '#15803D' },
        warning: { 50: '#FFFBEB', 100: '#FEF3C7', 500: '#F59E0B', 700: '#B45309' },
        danger: { 50: '#FEF2F2', 100: '#FEE2E2', 600: '#DC2626', 700: '#B91C1C' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.06)',
        lift: '0 4px 16px rgba(15,23,42,0.08)',
      },
    },
  },
  plugins: [],
}
