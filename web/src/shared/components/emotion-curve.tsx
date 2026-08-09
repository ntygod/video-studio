"use client";

import { useId } from "react";

type EmotionCurveProps = {
    values: number[];
    height?: number;
    className?: string;
};

export function EmotionCurve({ values, height = 150, className }: EmotionCurveProps) {
    const width = 560;
    const padX = 26;
    const padY = 14;
    const rawId = useId();
    const gid = "grad-" + rawId.replace(/[^a-zA-Z0-9]/g, "");

    if (!values || !values.length) {
        return <div className={className} style={{ height }} />;
    }

    const max = 10;
    const stepX = values.length > 1 ? (width - padX * 2) / (values.length - 1) : 0;
    const points = values.map((v, i) => {
        const x = values.length > 1 ? padX + i * stepX : width / 2;
        const y = padY + (1 - Math.max(0, Math.min(10, Number(v) || 0)) / max) * (height - padY * 2);
        return { x, y };
    });
    const line = points.map((p) => p.x.toFixed(1) + "," + p.y.toFixed(1)).join(" ");
    const area =
        "M" + points[0].x.toFixed(1) + "," + (height - padY) +
        " L" + line +
        " L" + points[points.length - 1].x.toFixed(1) + "," + (height - padY) + " Z";

    return (
        <div className={className}>
            <svg viewBox={"0 0 " + width + " " + height} className="w-full" style={{ height }} preserveAspectRatio="none">
                <defs>
                    <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--studio-primary)" stopOpacity="0.32" />
                        <stop offset="100%" stopColor="var(--studio-primary)" stopOpacity="0.02" />
                    </linearGradient>
                </defs>
                {[0, 2.5, 5, 7.5, 10].map((tick) => {
                    const y = padY + (1 - tick / max) * (height - padY * 2);
                    return (
                        <g key={tick}>
                            <line x1={padX} x2={width - padX} y1={y} y2={y} stroke="var(--studio-line)" strokeDasharray="3 4" strokeWidth="1" />
                            <text x={padX - 5} y={y + 3} textAnchor="end" fontSize="9" fill="var(--studio-faint)">{tick}</text>
                        </g>
                    );
                })}
                <path d={area} fill={"url(#" + gid + ")"} />
                <polyline points={line} fill="none" stroke="var(--studio-primary)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
                {points.map((p, i) => (
                    <g key={i}>
                        <circle cx={p.x} cy={p.y} r="4" fill="var(--studio-surface)" stroke="var(--studio-primary)" strokeWidth="2" />
                        <text x={p.x} y={height - 3} textAnchor="middle" fontSize="9" fill="var(--studio-faint)">{i + 1}</text>
                    </g>
                ))}
            </svg>
        </div>
    );
}

