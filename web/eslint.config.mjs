import tseslint from "typescript-eslint";

/**
 * UI 工艺的强制手段（docs/ui-craft.md §3.2 / §5）。
 *
 * - src 全量：禁止手抄容器（rounded-* + border + bg-[var(--s-*)]）、禁止 10px 字号。
 * - features：禁止直接 import antd，必须走 shared/ui。
 */
export default tseslint.config(
    {
        ignores: [".next/**", "node_modules/**", "public/**", "next-env.d.ts", "**/*.test.ts"],
    },
    {
        files: ["src/**/*.{ts,tsx}"],
        languageOptions: {
            parser: tseslint.parser,
            parserOptions: {
                ecmaVersion: "latest",
                sourceType: "module",
                ecmaFeatures: { jsx: true },
            },
        },
        rules: {
            "no-restricted-syntax": [
                "error",
                {
                    selector: "Literal[value=/rounded-(md|lg|xl).*border.*bg-\\[var\\(--s-/]",
                    message: "容器请用 <Surface> / <Card>，不要手写。见 docs/ui-craft.md §3",
                },
                {
                    selector: "Literal[value=/text-\\[10px\\]/]",
                    message: "字号最低 caption(11px)，不要用 10px。见 docs/ui-craft.md §2.2",
                },
            ],
        },
    },
    {
        files: ["src/features/**/*.{ts,tsx}"],
        rules: {
            "no-restricted-imports": [
                "error",
                {
                    paths: [
                        {
                            name: "antd",
                            message: "feature 代码不得直接引 antd，请走 shared/ui。见 docs/ui-craft.md §5",
                        },
                    ],
                },
            ],
        },
    },
);
