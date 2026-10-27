import type { Config } from "tailwindcss";

const token = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Inter Variable'", "Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // ARVA brand palette (fixed across themes)
        arva: {
          navy: "#0B132B",
          royal: "#1F3B8A",
          teal: "#00B4A6",
          cyan: "#7CC8FF",
          mist: "#E5E7EB",
          "bg-light": "#F8FAFC",
          "bg-dark": "#080F1F",
        },
        success: "#16A34A",
        warning: "#F59E0B",
        danger: "#DC2626",
        // Semantic theme tokens (switch with light/dark)
        background: token("background"),
        foreground: token("foreground"),
        surface: token("surface"),
        "surface-2": token("surface-2"),
        muted: token("muted"),
        "muted-foreground": token("muted-foreground"),
        border: token("border"),
        primary: token("primary"),
        "primary-foreground": token("primary-foreground"),
        accent: token("accent"),
        ring: token("ring"),
      },
      borderRadius: { xl: "0.875rem", "2xl": "1.125rem" },
      boxShadow: {
        card: "0 1px 2px rgb(11 19 43 / 0.04), 0 4px 16px rgb(11 19 43 / 0.04)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { "fade-in": "fade-in 220ms ease-out" },
    },
  },
  plugins: [],
} satisfies Config;
