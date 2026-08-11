#!/usr/bin/env node
/**
 * 对比度验收（docs/ui-craft.md §6 C6）：正文/次要文字/元信息在常见表面上 ≥ 4.5:1。
 *
 * 从 globals.css 读取两套主题的令牌值（含 color-mix 忽略，只取纯色），
 * 按实际使用组合计算 WCAG 对比度。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const ROOT = fileURLToPath(new URL("..", import.meta.url)).replace(/[\\/]$/, "");
const CSS = readFileSync(join(ROOT, "web", "src", "app", "globals.css"), "utf8");

function hexRgb(hex) {
    const value = hex.replace("#", "");
    const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
    return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
}

function luminance(rgb) {
    const linear = rgb.map((channel) =>
        channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4),
    );
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(a, b) {
    const l1 = luminance(hexRgb(a));
    const l2 = luminance(hexRgb(b));
    const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
    return (hi + 0.05) / (lo + 0.05);
}

function tokensOf(theme) {
    const block = CSS.slice(CSS.indexOf('html[data-theme="' + theme + '"]'));
    const nextTheme = block.indexOf('html[data-theme="' + (theme === "dark" ? "light" : "dark") + '"]', 1);
    const migration = block.indexOf("/* ── 迁移期");
    const cut = [nextTheme, migration].filter((index) => index > 0);
    const end = cut.length ? Math.min(...cut) : -1;
    const source = end > 0 ? block.slice(0, end) : block;
    const tokens = {};
    for (const match of source.matchAll(/(--s-[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})/g)) {
        tokens[match[1]] = match[2];
    }
    return tokens;
}

const THEMES = {
    dark: tokensOf("dark"),
    light: tokensOf("light"),
};

// 实际使用的文字/表面组合。
const PAIRS = [
    ["ink", "base"],
    ["ink", "panel"],
    ["ink", "raised"],
    ["ink", "overlay"],
    ["ink", "canvas"],
    ["text", "base"],
    ["text", "panel"],
    ["text", "raised"],
    ["text", "overlay"],
    ["text", "canvas"],
    ["muted", "base"],
    ["muted", "panel"],
    ["muted", "raised"],
    ["muted", "overlay"],
    ["muted", "canvas"],
    ["faint", "base"],
    ["faint", "panel"],
    ["faint", "raised"],
    ["faint", "overlay"],
    ["faint", "canvas"],
    ["action", "panel"],
    ["action", "base"],
    ["danger", "panel"],
    ["success", "panel"],
    ["warning", "panel"],
    ["info", "panel"],
    ["action-foreground", "action"],
];

let failed = false;
for (const theme of ["dark", "light"]) {
    const t = THEMES[theme];
    console.log("── " + theme + " ──");
    for (const [fgKey, bgKey] of PAIRS) {
        const fg = t["--s-" + fgKey];
        const bg = t["--s-" + bgKey];
        if (!fg || !bg) {
            console.error("  缺失令牌: " + fgKey + " / " + bgKey);
            failed = true;
            continue;
        }
        const ratio = contrast(fg, bg);
        const ok = ratio >= 4.5;
        if (!ok) failed = true;
        console.log((ok ? "  ✓ " : "  ✗ ") + fgKey.padEnd(16) + " on " + bgKey.padEnd(7) + " = " + ratio.toFixed(2));
    }
}

process.exit(failed ? 1 : 0);
