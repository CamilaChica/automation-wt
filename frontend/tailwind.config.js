/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: {
          dark: '#0B0F19',
          light: '#F8FAFC'
        },
        card: {
          dark: '#111827',
          'dark-elevated': '#1E293B',
          light: '#FFFFFF',
          'light-elevated': '#F1F5F9'
        },
        aero: {
          blue: '#12304A',
          'blue-light': '#C9A227',
          dark: '#0B1F33'
        },
        aog: {
          red: '#EF4444',
          'red-light': '#DC2626'
        },
        compliance: {
          green: '#10B981',
          'green-light': '#059669'
        },
        warning: {
          amber: '#C9A227',
          'amber-light': '#A88313'
        }
      },
      fontFamily: {
        display: ['Montserrat', 'sans-serif'],
        sans: ['Montserrat', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace']
      },
      animation: {
        'pulse-fast': 'pulse 1.2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow-red': 'glowRed 2s infinite alternate',
      },
      keyframes: {
        glowRed: {
          '0%': { boxShadow: '0 0 5px rgba(239, 68, 68, 0.4)' },
          '100%': { boxShadow: '0 0 18px rgba(239, 68, 68, 0.9)' },
        }
      }
    },
  },
  plugins: [],
}
