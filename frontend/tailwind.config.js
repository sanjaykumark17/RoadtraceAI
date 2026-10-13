/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        speed: {
          low: "#10b981",    // < 40 km/h (Emerald Green)
          med: "#f59e0b",    // 40 - 80 km/h (Amber)
          high: "#ef4444",   // > 80 km/h (Crimson Red)
        },
        swiss: {
          red: "#dc2626",
          dark: "#0a0a0a",
          card: "#121212",
          border: "#262626",
        },
      },
      letterSpacing: {
        tighter: "-0.04em",
        tight: "-0.02em",
        widest: "0.15em",
      },
    },
  },
  plugins: [],
};
