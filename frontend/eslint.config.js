import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import ts from "typescript-eslint";

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...vue.configs["flat/essential"],
  {
    files: ["**/*.vue"],
    languageOptions: { parserOptions: { parser: ts.parser } },
    rules: {
      "no-undef": "off",
      "vue/multi-word-component-names": ["error", { ignores: ["App"] }],
    },
  },
];
