"use client";

/** 时间刻度（T4.F1）。 */
export function Ruler({ duration, pxPerSec }: { duration: number; pxPerSec: number }) {
    const step = pxPerSec >= 60 ? 1 : 2;
    const laneWidth = Math.max(200, duration * pxPerSec);
    const marks: number[] = [];
    for (let t = 0; t <= Math.ceil(duration); t += step) marks.push(t);
    return (
        <div className="flex w-max min-w-full border-b border-[var(--hairline)]">
            <div className="flex h-6 w-24 shrink-0 items-center border-r border-[var(--hairline)] px-2 text-caption text-[var(--s-faint)]">轨道</div>
            <div className="relative h-6 shrink-0" style={{ width: laneWidth }}>
                {marks.map((tick) => (
                    <div key={tick} className="absolute top-0 flex h-full items-start" style={{ left: tick * pxPerSec }}>
                        <span className="h-2 w-px bg-[var(--hairline-strong)]" />
                        <span className="ml-1 text-caption leading-3 text-[var(--s-faint)]">{tick}s</span>
                    </div>
                ))}
            </div>
        </div>
    );
}
