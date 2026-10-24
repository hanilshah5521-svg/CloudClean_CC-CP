/** @type {import('tailwindcss').Config} */
// "Industrial Precision" design tokens. Every color in the UI comes from here.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // Each color is a CSS variable holding "R G B" (light and dark sets in
      // src/index.css), so opacity modifiers like bg-ok-soft/60 keep working.
      colors: {
        canvas: v("canvas"), // workspace background (warm off-white / graphite)
        panel: v("panel"), // sidebar
        surface: v("surface"), // cards, fields, drawer
        line: v("line"), // 1px hairlines
        "line-strong": v("line-strong"), // hover borders
        track: v("track"), // empty part of bars, skeletons
        ink: v("ink"), // primary text
        sub: v("sub"), // secondary text
        faint: v("faint"), // labels, captions
        scrim: v("scrim"), // behind modals and sheets
        shade: v("shade"), // shadows
        accent: { DEFAULT: v("accent"), hover: v("accent-hover"), soft: v("accent-soft"), ink: v("accent-ink") },
        ok: { DEFAULT: v("ok"), ink: v("ok-ink"), soft: v("ok-soft") },
        warn: { DEFAULT: v("warn"), ink: v("warn-ink"), soft: v("warn-soft") },
        bad: { DEFAULT: v("bad"), ink: v("bad-ink"), soft: v("bad-soft") },
        info: { DEFAULT: v("info"), ink: v("info-ink"), soft: v("info-soft") },
        tier: { drive: v("tier-drive"), trash: v("tier-trash"), gmail: v("tier-gmail"), s3: v("tier-s3") },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: { DEFAULT: "6px", md: "6px", lg: "8px" },
    },
  },
  plugins: [],
};
