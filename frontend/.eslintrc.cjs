module.exports = {
  root: true,

  // ── Environment globals ─────────────────────────────────────────────────────
  env: {
    browser: true,
    es2022: true,
    node: true,
  },

  // ── Parser options ──────────────────────────────────────────────────────────
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: {
      jsx: true,
    },
  },

  // ── Plugins ─────────────────────────────────────────────────────────────────
  plugins: ["react", "react-hooks", "react-refresh"],

  // ── Extend shared configs ────────────────────────────────────────────────────
  extends: [
    "eslint:recommended",
    "plugin:react/recommended",
    "plugin:react/jsx-runtime",         // no need to import React in every file
    "plugin:react-hooks/recommended",
  ],

  // ── Per-project settings ────────────────────────────────────────────────────
  settings: {
    react: {
      version: "detect",
    },
  },

  // ── Rules ───────────────────────────────────────────────────────────────────
  rules: {
    // React
    "react/prop-types": "off",           // project doesn't use PropTypes
    "react/display-name": "off",         // many inline anonymous components

    // React Hooks — warn so developers notice, but don't block running
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",

    // React Refresh
    "react-refresh/only-export-components": [
      "warn",
      { allowConstantExport: true },
    ],

    // General JS
    "no-unused-vars": "off",
    "no-empty": "off",
    "no-console": "off",                 // project intentionally uses console
    "no-undef": "warn",                  // warn instead of error for undefined variables
  },

  // ── Ignore build artefacts ──────────────────────────────────────────────────
  ignorePatterns: ["dist", "node_modules", "public"],
};
