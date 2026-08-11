"use client";

import { cn } from "@/shared/lib/utils";

/** 一个镜头多个候选时的圆点切换选片。 */
export function ShotCandidates({
    count,
    active,
    onChange,
}: {
    count: number;
    active: number;
    onChange: (index: number) => void;
}) {
    if (count <= 1) return null;
    return (
        <div className="flex items-center gap-1">
            {Array.from({ length: count }, (_, index) => (
                <button
                    key={index}
                    type="button"
                    aria-label={`候选 ${index + 1}`}
                    onClick={() => onChange(index)}
                    className={cn(
                        "size-2 rounded-full transition-colors",
                        index === active
                            ? "bg-[var(--s-ink)]"
                            : "bg-[var(--hairline)] hover:bg-[var(--s-faint)]",
                    )}
                />
            ))}
        </div>
    );
}
