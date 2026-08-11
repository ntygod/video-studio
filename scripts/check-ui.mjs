#!/usr/bin/env node
/**
 * UI 工艺验收（docs/ui-craft.md §6 量化验收）。
 *
 * 1. 违规字号 text-[10px] = 0
 * 2. 手抄容器 rounded-(md|lg) border.*bg-[var = 0（features/ 下）
 * 3. feature 代码不得直接引 antd = 0
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url)).replace(/[\\/]$/, "");
const SRC = join(ROOT, "web", "src");

function walk(dir) {
    const out = [];
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) out.push(...walk(full));
        else if (/\.(ts|tsx)$/.test(entry)) out.push(full);
    }
    return out;
}

const files = walk(SRC);
const violations = { tiny: [], container: [], antd: [] };

for (const file of files) {
    const source = readFileSync(file, "utf8");
    const rel = relative(SRC, file);
    if (/text-\[10px\]/.test(source)) violations.tiny.push(rel);
    if (rel.startsWith("features") && /rounded-(md|lg)\s+border.*bg-\[var/.test(source)) violations.container.push(rel);
    if (rel.startsWith("features") && /from ["']antd["']/.test(source)) violations.antd.push(rel);
}

let failed = false;

function report(label, key) {
    if (violations[key].length > 0) {
        failed = true;
        console.error("✗ " + label + " = " + violations[key].length + "（目标 0）");
        for (const file of violations[key].slice(0, 20)) console.error("    " + file);
        if (violations[key].length > 20) console.error("    … 还有 " + (violations[key].length - 20) + " 个");
    } else {
        console.log("✓ " + label + " = 0");
    }
}

report("text-[10px]", "tiny");
report("features 手抄容器", "container");
report("features 直接引 antd", "antd");

process.exit(failed ? 1 : 0);
