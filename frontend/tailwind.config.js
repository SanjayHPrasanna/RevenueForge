/** @type {import('tailwindcss').Config} */
// Every colour is a theme token (src/index.css: :root = light, [data-theme="dark"] = dark), so one set of classes
// renders both themes. Tokens are stored as "r g b" so opacity modifiers (bg-brand-500/20) keep working.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // accent (blue) scale: 50-200 tints for fills, 400-600 the accent itself, 700-950 accent text and ink
        brand: { 50: v("b50"), 100: v("b100"), 200: v("b200"), 400: v("b400"), 500: v("b500"), 600: v("b600"), 700: v("b700"), 800: v("b800"), 900: v("b900"), 950: v("b950") },
        // warm secondary (deadlines, "running", highlights)
        ember: { 50: v("e50"), 100: v("e100"), 400: v("e400"), 500: v("e500"), 600: v("e600"), 700: v("e700") },
        ink: { DEFAULT: v("ink"), soft: v("ink-2"), muted: v("muted"), faint: v("faint") },
        paper: v("sunken"),
        surface: v("surface"),
        midnight: { 900: v("m900"), 950: v("m950"), 990: v("m990") },
        // hairlines are a fixed, faint tint of the ink colour so they read the same on glass in both themes
        line: { DEFAULT: "rgb(var(--line) / 0.12)", soft: "rgb(var(--line) / 0.075)" },
        // match status: colour-blind-safe hues, each with a text shade and a soft fill
        fit: { strong: v("fit-strong"), partial: v("fit-partial"), gap: v("fit-gap"), confirm: v("fit-confirm"),
               "strong-ink": v("fit-strong-ink"), "partial-ink": v("fit-partial-ink"), "gap-ink": v("fit-gap-ink"), "confirm-ink": v("fit-confirm-ink"),
               "strong-bg": v("fit-strong-bg"), "partial-bg": v("fit-partial-bg"), "gap-bg": v("fit-gap-bg"), "confirm-bg": v("fit-confirm-bg") },
        ok: { DEFAULT: v("ok"), bg: v("ok-bg") },
      },
      fontFamily: {
        sans: ["'Urbanist Variable'", "Urbanist", "system-ui", "-apple-system", "'Segoe UI'", "sans-serif"],
        display: ["'Urbanist Variable'", "Urbanist", "system-ui", "sans-serif"],
        doc: ["'Newsreader Variable'", "'Newsreader'", "Georgia", "serif"],
      },
      boxShadow: {
        card: "inset 0 0 0 1px var(--glass-rim), inset 0 1px 0 var(--glass-top), var(--shadow)",
        lift: "inset 0 0 0 1px var(--glass-rim), var(--shadow-lg)",
        hover: "inset 0 0 0 1px var(--glass-rim), inset 0 1px 0 var(--glass-top), var(--shadow-lg)",
        float: "inset 0 0 0 1px var(--glass-rim), var(--shadow-lg)",
        btn: "inset 0 1px 0 rgba(255,255,255,.4), 0 10px 22px -10px rgb(var(--b500) / .55)",
      },
      borderRadius: { xl2: "16px", "2xl": "20px", "3xl": "26px" },
      transitionTimingFunction: { apple: "cubic-bezier(.22,1,.36,1)", spring: "cubic-bezier(.2,.9,.25,1.15)" },
    },
  },
  plugins: [],
};
