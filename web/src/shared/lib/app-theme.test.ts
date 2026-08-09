import assert from "node:assert/strict";
import test from "node:test";

import { getAntThemeConfig, paletteFor } from "./app-theme.ts";

/**
 * 这些断言刻意不校验具体色值。
 * <p>
 * 旧版本把 hex 写死在断言里，调一次色板就红一片，结果是没人再跑它。
 * 这里只保证结构完整、两套主题字段一致、以及主色确实来自调色板。
 */

const PALETTE_KEYS = Object.keys(paletteFor("dark"));

test("两套调色板的字段完全一致", () => {
    assert.deepEqual(Object.keys(paletteFor("light")).sort(), PALETTE_KEYS.sort());
});

test("调色板不存在空值", () => {
    for (const theme of ["light", "dark"] as const) {
        const palette = paletteFor(theme) as Record<string, string>;
        for (const key of PALETTE_KEYS) {
            assert.ok(palette[key], `${theme} 主题缺少 ${key}`);
        }
    }
});

test("antd 主题的主色与语义色取自调色板", () => {
    for (const theme of ["light", "dark"] as const) {
        const palette = paletteFor(theme);
        const config = getAntThemeConfig(theme);

        assert.equal(config.token?.colorPrimary, palette.action);
        assert.equal(config.token?.colorError, palette.danger);
        assert.equal(config.token?.colorSuccess, palette.success);
        assert.equal(config.token?.colorBgLayout, palette.bg);
        assert.equal(config.token?.colorText, palette.ink);
    }
});

test("弹窗类容器统一使用 surface 作为底色", () => {
    for (const theme of ["light", "dark"] as const) {
        const palette = paletteFor(theme);
        const modal = getAntThemeConfig(theme).components?.Modal;

        assert.equal(modal?.contentBg, palette.surface);
        assert.equal(modal?.headerBg, palette.surface);
        assert.equal(modal?.footerBg, palette.surface);
    }
});

test("暗色与浅色使用不同的 antd 算法", () => {
    assert.notEqual(getAntThemeConfig("dark").algorithm, getAntThemeConfig("light").algorithm);
});
