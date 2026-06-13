import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand & accent (DESIGN.md colors)
        primary: { DEFAULT: "#FCD535", active: "#f0b90b", disabled: "#3a3a1f" },
        ink: "#181a20",
        body: { DEFAULT: "#eaecef", onlight: "#181a20" },
        muted: { DEFAULT: "#707a8a", strong: "#929aa5" },
        hairline: { onlight: "#eaecef", ondark: "#2b3139" },
        "border-strong": "#cdd1d6",
        canvas: { light: "#ffffff", dark: "#0b0e11" },
        surface: {
          "card-dark": "#1e2329",
          "elevated-dark": "#2b3139",
          "soft-light": "#fafafa",
          "strong-light": "#f5f5f5",
        },
        "on-primary": "#181a20",
        "on-dark": "#ffffff",
        trading: { up: "#0ecb81", down: "#f6465d" },
        "accent-turquoise": "#2dbdb6",
        info: "#3b82f6",
      },
      fontFamily: {
        display: ['"Inter"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"', "sans-serif"],
        number: ['"IBM Plex Sans"', '"Inter"', "monospace"],
      },
      fontSize: {
        "hero-display": ["64px", { lineHeight: "1.1", letterSpacing: "-1px", fontWeight: "700" }],
        "display-lg": ["48px", { lineHeight: "1.1", letterSpacing: "-0.5px", fontWeight: "700" }],
        "display-md": ["40px", { lineHeight: "1.15", letterSpacing: "-0.3px", fontWeight: "600" }],
        "display-sm": ["32px", { lineHeight: "1.2", fontWeight: "600" }],
        "title-lg": ["24px", { lineHeight: "1.3", fontWeight: "600" }],
        "title-md": ["20px", { lineHeight: "1.35", fontWeight: "600" }],
        "title-sm": ["16px", { lineHeight: "1.4", fontWeight: "600" }],
        "number-display": ["40px", { lineHeight: "1.1", letterSpacing: "-0.3px", fontWeight: "700" }],
        "number-md": ["16px", { lineHeight: "1.4", fontWeight: "500" }],
        "number-sm": ["14px", { lineHeight: "1.4", fontWeight: "500" }],
        "body-md": ["14px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-sm": ["13px", { lineHeight: "1.5", fontWeight: "400" }],
        caption: ["12px", { lineHeight: "1.4", fontWeight: "500" }],
        button: ["14px", { lineHeight: "1", fontWeight: "600" }],
        "nav-link": ["14px", { lineHeight: "1.4", fontWeight: "500" }],
      },
      borderRadius: { xs: "2px", sm: "4px", md: "6px", lg: "8px", xl: "12px", pill: "9999px" },
      spacing: { xxs: "4px", xs: "8px", sm: "12px", md: "16px", lg: "24px", xl: "32px", xxl: "48px", section: "80px" },
    },
  },
  plugins: [],
};
export default config;
