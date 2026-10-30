import { createPreset } from "@basicbar/ui/tailwind-preset";

/**
 * ansehBAR design tokens.
 *
 * Structure and conventions (shade semantics, dark mode, font, motion) come
 * from the shared @basicbar/ui preset; the OKLCH color ramps below are this
 * tool's identity and stay here. The generated ramps start from the Copier
 * answers (brand hue 335, neutral hue 220) — fine-tune
 * chroma/lightness per shade for the final identity (WCAG-AA targets: CTAs
 * use brand-400 with dark ink text, brand-600 is the focus color, brand-700
 * is accent text on white, slate-400 on white ≥ 4.5:1).
 */

/** @type {import('tailwindcss').Config} */
export default {
  presets: [
    createPreset({
      colors: {
        // Keep the `/ <alpha-value>` placeholder on every token — without it
        // Tailwind's opacity modifier (e.g. `bg-slate-900/90`) renders
        // transparent.
        slate: {
          50: "oklch(0.985 0.002 220 / <alpha-value>)",
          100: "oklch(0.962 0.003 220 / <alpha-value>)",
          200: "oklch(0.922 0.005 220 / <alpha-value>)",
          300: "oklch(0.868 0.007 220 / <alpha-value>)",
          400: "oklch(0.577 0.011 220 / <alpha-value>)",
          500: "oklch(0.498 0.013 220 / <alpha-value>)",
          600: "oklch(0.43 0.014 220 / <alpha-value>)",
          700: "oklch(0.36 0.013 220 / <alpha-value>)",
          800: "oklch(0.28 0.011 220 / <alpha-value>)",
          900: "oklch(0.215 0.011 220 / <alpha-value>)",
          950: "oklch(0.16 0.009 220 / <alpha-value>)",
        },
        brand: {
          50: "oklch(0.975 0.015 335 / <alpha-value>)",
          100: "oklch(0.945 0.04 335 / <alpha-value>)",
          200: "oklch(0.9 0.07 335 / <alpha-value>)",
          300: "oklch(0.865 0.1 335 / <alpha-value>)",
          400: "oklch(0.84 0.13 335 / <alpha-value>)",
          500: "oklch(0.78 0.13 335 / <alpha-value>)",
          600: "oklch(0.62 0.12 335 / <alpha-value>)",
          700: "oklch(0.5 0.1 335 / <alpha-value>)",
          800: "oklch(0.42 0.08 335 / <alpha-value>)",
          900: "oklch(0.35 0.065 335 / <alpha-value>)",
          950: "oklch(0.26 0.045 335 / <alpha-value>)",
        },
      },
    }),
  ],
  // The @basicbar/ui components carry Tailwind classes of their own — scan
  // the package dist so those classes reach the generated CSS.
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./node_modules/@basicbar/ui/dist/**/*.js",
  ],
  plugins: [],
};
