#!/usr/bin/env node
/**
 * 幽灵令牌扫描（docs/ui-craft.md §6 验收第 1 条）。
 *
 * 扫描 web/src 里所有 var(--x) 引用，与 globals.css 中定义的令牌做 diff；
 * 引用到不存在的令牌即 fail（exit 1）。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url)).replace(/[\\/]$/, "");
const SRC = join(ROOT, "web", "src");
const CSS = join(SRC, "app", "globals.css");

function walk(dir) {
    const out = [];
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
            out.push(...walk(full));
        } else if (/\.(css|ts|tsx|mjs)$/.test(entry)) {
            out.push(full);
        }
    }
    return out;
}

function definedTokens(cssPath) {
    const css = readFileSync(cssPath, "utf8");
    const tokens = new Set();
    const re = /(?:^|\s|,)(--[a-z0-9-]+)\s*:/gi;
    for (const match of css.matchAll(re)) {
        tokens.add(match[1].replace(/^--/, ""));
    }
    return tokens;
}

const tokens = definedTokens(CSS);
const ghosts = new Map(); // name -> files
const legacy = new Map(); // --studio-* refs outside globals.css（迁移目标：0）
const files = walk(SRC).filter((file) => !file.endsWith("globals.css"));

for (const file of files) {
    const source = readFileSync(file, "utf8");
    const re = /var\(--([a-z0-9-]+)/g;
    for (const match of source.matchAll(re)) {
        const name = match[1];
        if (!tokens.has(name)) {
            if (!ghosts.has(name)) ghosts.set(name, []);
            ghosts.get(name).push(relative(SRC, file));
        } else if (name.startsWith("studio-") && !file.includes(sep + "app" + sep)) {
            if (!legacy.has(name)) legacy.set(name, []);
            legacy.get(name).push(relative(SRC, file));
        }
    }
}

let failed = false;

if (ghosts.size > 0) {
    failed = true;
    console.error("✗ 幽灵令牌（引用了不存在的令牌）：");
    for (const [name, refs] of [...ghosts.entries()].sort()) {
        console.error("  --" + name + "  ->  " + refs.length + " 处：");
        for (const ref of refs.slice(0, 8)) console.error("      " + ref);
        if (refs.length > 8) console.error("      … 还有 " + (refs.length - 8) + " 处");
    }
} else {
    console.log("✓ 幽灵令牌 = 0");
}

if (legacy.size > 0) {
    const total = [...legacy.values()].reduce((n, v) => n + v.length, 0);
    console.warn("⚠ --studio-* 迁移剩余 " + total + " 处引用（目标 0）：");
    for (const [name, refs] of [...legacy.entries()].sort()) {
        console.warn("  --" + name + ": " + refs.length + " 处");
    }
} else {
    console.log("✓ --studio-* 已全部迁移到 --s-*");
}

process.exit(failed ? 1 : 0);
