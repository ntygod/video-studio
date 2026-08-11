"use client";

import { useRef, useState } from "react";
import { Plus } from "lucide-react";

import type { Artifact, CreativeUnit } from "@/services/api";
import { MentionPicker, type ContextRef } from "./mention-picker";
import { Chip, Text } from "@/shared/ui";

export type { ContextRef } from "./mention-picker";

/** 上下文条：chip 列表 + 添加 + token 预估。视觉规格见 docs/ui-redesign.md §4.2(b)。 */
export function ContextBar({
    refs,
    onChange,
    units,
    artifacts,
    tokenEstimate,
}: {
    refs: ContextRef[];
    onChange: (refs: ContextRef[]) => void;
    units: CreativeUnit[];
    artifacts: Artifact[];
    tokenEstimate?: number;
}) {
    const [pickerOpen, setPickerOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement | null>(null);

    // 关闭时把焦点还给“添加上下文”按钮，便于键盘用户继续 Tab。
    const closePicker = () => {
        setPickerOpen(false);
        requestAnimationFrame(() => triggerRef.current?.focus());
    };

    const remove = (index: number) => {
        onChange(refs.filter((_, itemIndex) => itemIndex !== index));
    };

    return (
        <div className="relative flex flex-wrap items-center gap-1.5 border-b border-[var(--hairline)] px-3 py-2">
            {refs.map((ref, index) => (
                <Chip
                    key={`${ref.type}-${ref.id || ref.section || index}`}
                    removable
                    label={ref.label}
                    onRemove={() => remove(index)}
                >
                    {ref.label}
                </Chip>
            ))}
            <button
                type="button"
                ref={triggerRef}
                aria-haspopup="dialog"
                aria-expanded={pickerOpen}
                onClick={() => setPickerOpen(!pickerOpen)}
                className="flex items-center gap-1 rounded-full border border-dashed border-[var(--hairline)] px-2 py-0.5 text-caption text-[var(--s-faint)] transition-colors hover:border-[var(--hairline-strong)] hover:text-[var(--s-ink)]"
            >
                <Plus className="size-3" />
                添加上下文
            </button>
            <Text variant="caption" tone="faint" className="ml-auto shrink-0">
                {tokenEstimate ? `~${tokenEstimate} tokens` : ""}
            </Text>
            {pickerOpen ? (
                <MentionPicker
                    units={units}
                    artifacts={artifacts}
                    onClose={closePicker}
                    onPick={(ref) => {
                        onChange([...refs, ref]);
                        closePicker();
                    }}
                />
            ) : null}
        </div>
    );
}
