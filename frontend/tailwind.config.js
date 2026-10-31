/** @type {import('tailwindcss').Config} */
/*
 * Warm cream industrial palette.
 * Token names (primary / secondary / success / warning / danger / slate) are kept so every
 * existing component picks up the new palette without per-file rewrites.
 *   primary   → bronze accent (#A68A64)         REAL provenance, focus, links
 *   secondary → dusty sage (#6E8582)             SYNTHETIC provenance
 *   success   → muted olive (#78866B)            AUTO_RESOLVE, passed checks
 *   warning   → amber clay (#C18D4D)             REQUIRES_HUMAN_REVIEW, loops
 *   danger    → brick (#B9685D)                  errors, failed checks
 *   slate     → warm stone greys                 neutral UI
 */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F7F4EC',
        well: '#EFE9DD',
        surface: '#FFFCF5',
        white: '#FFFCF5',
        ink: '#17140F',
        muted: '#4A453D',
        line: '#E5DED1',
        primary: { 50: '#F7F1E7', 100: '#EFE5D4', 200: '#E0D0B5', 300: '#C9B28E', 500: '#A68A64', 600: '#8C7250', 700: '#6E5A3E' },
        secondary: { 50: '#EEF2F1', 100: '#DCE5E3', 500: '#6E8582', 600: '#5C726F', 700: '#475957' },
        success: { 50: '#F0F2EB', 100: '#E0E6D7', 500: '#78866B', 600: '#66745A', 700: '#4F5B45' },
        warning: { 50: '#FBF3E8', 100: '#F4E3CB', 500: '#C18D4D', 600: '#A9773A', 700: '#8A5F2D' },
        danger: { 50: '#FAEEEC', 100: '#F2D9D5', 500: '#B9685D', 600: '#A9594E', 700: '#8E463D' },
        slate: {
          50: '#FAF7F0', 100: '#F1ECE1', 200: '#E5DED1', 300: '#D3CABA', 400: '#8A8170',
          500: '#6B6457', 600: '#4F4A42', 700: '#3B3731', 800: '#2A2620', 900: '#17140F',
        },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 0 rgba(48,44,37,0.04)',
        lift: '0 8px 24px rgba(48,44,37,0.10)',
      },
    },
  },
  plugins: [],
}
