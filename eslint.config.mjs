import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

// eslint-config-next 15.x expõe configs no formato eslintrc legado
// (objeto com `extends`), não flat-config. FlatCompat.extends() converte
// "next/core-web-vitals" e "next/typescript" para o flat config do ESLint 9.
const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      // Worktrees do Claude Code: cópias completas do app — não lintar.
      ".claude/**",
      // Pipeline Python — fora do escopo do ESLint.
      "scripts/**",
    ],
  },
];

export default eslintConfig;
