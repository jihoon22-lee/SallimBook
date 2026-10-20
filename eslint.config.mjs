// @ts-check
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores([
    "**/dist/",
    "**/.cache/",
    "**/test-results/",
    "**/playwright-report/",
    "**/coverage/",
    "apps/client/android/",
    "packages/api-client/src/schema.d.ts",
  ]),
  { linterOptions: { reportUnusedDisableDirectives: "error" } },
  {
    files: ["**/*.{ts,tsx,mts,cts,js,mjs,cjs}"],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    rules: {
      // `{ card_id: _card, ...cash }` and `_args` deliberately drop a value by name.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", destructuredArrayIgnorePattern: "^_" },
      ],
    },
  },
  {
    // React rules cover app code only: Playwright `test.use` and fixtures are not React hooks.
    files: ["apps/client/src/**/*.{ts,tsx}"],
    extends: [reactHooks.configs.flat.recommended, jsxA11y.flatConfigs.recommended],
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // Diagnostics for React Compiler, which this app does not use (see PR).
      "react-hooks/config": "off",
      "react-hooks/error-boundaries": "off",
      "react-hooks/gating": "off",
      "react-hooks/globals": "off",
      "react-hooks/immutability": "off",
      "react-hooks/incompatible-library": "off",
      "react-hooks/preserve-manual-memoization": "off",
      "react-hooks/purity": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/set-state-in-render": "off",
      "react-hooks/static-components": "off",
      "react-hooks/unsupported-syntax": "off",
      "react-hooks/use-memo": "off",
      // Scrollable tables are focusable regions so keyboard users can scroll them (WCAG 2.1.1).
      "jsx-a11y/no-noninteractive-tabindex": [
        "error",
        { tags: [], roles: ["tabpanel", "region"], allowExpressionValues: true },
      ],
    },
  },
  {
    // Synthetic Playwright mocks read browser-side test hooks (`window as any`) and fixture JSON.
    files: ["apps/client/tests/**/*.ts", "apps/client/integration/**/*.ts"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
]);
