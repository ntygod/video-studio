"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getTurn, type AgentTurn, type AgentTurnEvent, type TurnStep } from "@/services/api";
import { subscribeTurnStream } from "./sse-client";

export type TurnStreamState = {
    turn: AgentTurn | null;
    steps: TurnStep[];
    text: string;
    status: "idle" | AgentTurn["status"];
    entities: AgentTurn["created_entities"];
    proposals: Array<Record<string, unknown>>;
};

const INITIAL: TurnStreamState = {
    turn: null,
    steps: [],
    text: "",
    status: "idle",
    entities: [],
    proposals: [],
};

/**
 * 订阅某个 Agent 回合，把 SSE 事件归并成 {steps[], text, proposals[], status}。
 * <p>
 * SSE 不可用时自动降级为轮询 GET /api/turns/{id}。
 */
export function useTurnStream(conversationId: string | null, turnId: string | null) {
    const [state, setState] = useState<TurnStreamState>(INITIAL);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const applyTurn = useCallback((turn: AgentTurn) => {
        setState((previous) => ({
            ...previous,
            turn,
            steps: turn.steps && turn.steps.length ? turn.steps : previous.steps,
            status: turn.status,
            entities: turn.created_entities || [],
        }));
    }, []);

    useEffect(() => {
        setState(INITIAL);
        if (!conversationId || !turnId) return;
        let closed = false;

        getTurn(turnId)
            .then((turn) => {
                if (!closed) applyTurn(turn);
            })
            .catch(() => {
                /* 回合可能刚创建，种子请求失败时等待 SSE/轮询 */
            });

        const stopPolling = () => {
            if (pollRef.current) {
                clearInterval(pollRef.current);
                pollRef.current = null;
            }
        };

        const unsubscribe = subscribeTurnStream(conversationId, turnId, {
            onEvent(event) {
                if (closed) return;
                switch (event.type) {
                    case "token":
                        setState((previous) => ({
                            ...previous,
                            text: previous.text + String(event.text || ""),
                        }));
                        break;
                    case "step.start":
                        setState((previous) => {
                            const step: TurnStep = {
                                id: String(event.step_id || `step-${previous.steps.length}`),
                                turn_id: turnId,
                                seq: previous.steps.length + 1,
                                kind: "tool",
                                tool_name: String(event.tool || ""),
                                arguments: {},
                                result: {},
                                summary: String(event.args_preview || ""),
                                status: "running",
                                error: "",
                                duration_ms: 0,
                                created_at: Date.now() / 1000,
                            };
                            return { ...previous, steps: [...previous.steps, step] };
                        });
                        break;
                    case "step.done":
                        setState((previous) => ({
                            ...previous,
                            steps: previous.steps.map((step) =>
                                step.id === event.step_id
                                    ? {
                                          ...step,
                                          status: event.ok ? "ok" : "failed",
                                          duration_ms: Number(event.duration_ms || 0),
                                          summary: String(event.summary || step.summary),
                                          error: event.ok ? "" : step.error,
                                      }
                                    : step,
                            ),
                        }));
                        break;
                    case "entity":
                        if (event.entity) {
                            const entity = event.entity as AgentTurn["created_entities"][number];
                            setState((previous) => ({
                                ...previous,
                                entities: [...previous.entities, entity],
                            }));
                        }
                        break;
                    case "proposal":
                        if (event.proposal) {
                            setState((previous) => ({
                                ...previous,
                                proposals: [...previous.proposals, event.proposal as Record<string, unknown>],
                            }));
                        }
                        break;
                    case "error":
                        if (!event.recoverable) {
                            setState((previous) => ({ ...previous, status: "failed" }));
                        }
                        break;
                    case "done":
                        stopPolling();
                        setState((previous) => ({
                            ...previous,
                            status: event.failed ? "failed" : event.canceled ? "canceled" : "succeeded",
                        }));
                        break;
                    default:
                        break;
                }
            },
            onFallback() {
                if (closed) return;
                stopPolling();
                pollRef.current = setInterval(() => {
                    getTurn(turnId)
                        .then((turn) => {
                            if (closed) return;
                            applyTurn(turn);
                            if (turn.status !== "running") stopPolling();
                        })
                        .catch(() => {});
                }, 2000);
            },
        });

        return () => {
            closed = true;
            stopPolling();
            unsubscribe();
        };
    }, [applyTurn, conversationId, turnId]);

    return state;
}
