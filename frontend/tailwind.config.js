/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // RevenueForge brand
        brand: { 50: "#EAF5FB", 100: "#CFE8F5", 200: "#9FD1EB", 400: "#3BA3D6", 500: "#118AC3", 600: "#067AB0", 700: "#0B638E", 800: "#125C7E", 900: "#0C3D55", 950: "#082B3D" },
        ember: { 50: "#FEF3EB", 100: "#FDE2CF", 400: "#F79A5E", 500: "#F5833A", 600: "#DD6A22" },
        ink: { DEFAULT: "#10222E", soft: "#3D4F5B", muted: "#5F707B", faint: "#8A99A3" },
        paper: "#F3F6F8",
        // midnight surfaces for the cinematic areas (landing hero, sign-in, sidebar)
        midnight: { 900: "#0A2433", 950: "#061823", 990: "#030F17" },
        line: { DEFAULT: "#DCE3E8", soft: "#E8EDF0" },
        // match status: validated for colour-blind separation (strong blue-teal, partial amber, gap red; confirm drawn hollow)
        fit: { strong: "#1A82AE", partial: "#D09516", gap: "#CC3D3D", confirm: "#8A99A3",
               "strong-ink": "#13698D", "partial-ink": "#8A5F07", "gap-ink": "#A8302F", "confirm-ink": "#56656F" },
        // "good" status (approved, won, saved), never used for match strength
        ok: { DEFAULT: "#17876A", bg: "#E3F4EE" },
      },
      fontFamily: {
        sans: ["'Hanken Grotesk Variable'", "'Hanken Grotesk'", "system-ui", "sans-serif"],
        doc: ["'Newsreader Variable'", "'Newsreader'", "Georgia", "serif"],
        display: ["'Newsreader Variable'", "'Newsreader'", "Georgia", "serif"],
      },
      boxShadow: {
        card: "0 0 0 1px rgba(16,34,46,.04), 0 1px 2px rgba(16,34,46,.05), 0 2px 6px -2px rgba(16,34,46,.05)",
        lift: "0 0 0 1px rgba(16,34,46,.04), 0 24px 48px -18px rgba(8,43,61,.32), 0 8px 16px -8px rgba(8,43,61,.12)",
        hover: "0 0 0 1px rgba(16,34,46,.05), 0 14px 30px -14px rgba(8,43,61,.26), 0 4px 10px -4px rgba(8,43,61,.08)",
        float: "0 50px 100px -30px rgba(3,18,28,.55), 0 30px 60px -30px rgba(3,18,28,.45), inset 0 1px 0 rgba(255,255,255,.6)",
        btn: "0 1px 0 rgba(255,255,255,.18) inset, 0 1px 2px rgba(8,43,61,.25), 0 4px 10px -4px rgba(8,43,61,.35)",
      },
      borderRadius: { xl2: "14px" },
      transitionTimingFunction: { apple: "cubic-bezier(.22,.61,.36,1)", spring: "cubic-bezier(.2,.9,.25,1.15)" },
    },
  },
  plugins: [],
};
