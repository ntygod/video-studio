"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
    getTurn,
    type AgentTurn,
    type AgentTurnEvent,
    type TurnStep,
} from "@/services/api";
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

function hasEntity(
    entities: AgentTurn["created_entities"],
    candidate: AgentTurn["created_entities"][number],
): boolean {
    return entities.some(
        (entity) =>
            entity.type === candidate.type && entity.id === candidate.id,
    );
}

/**
 * 订阅某个 Agent 回合，把 SSE 事件归并成 {steps[], text, proposals[], status}。
 *
 * RuntimeTaskEvent 可能在断线重连或崩溃恢复后重放，因此所有实体和 Step 归并都
 * 必须按稳定 ID 幂等；最终 message 事件用于替换可能丢失的 live token 文本。
 */
export function useTurnStream(
    conversationId: string | null,
    turnId: string | null,
) {
    const [state, setState] = useState<TurnStreamState>(INITIAL);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const applyTurn = useCallback((turn: AgentTurn) => {
        setState((previous) => ({
            ...previous,
            turn,
            steps:
                turn.steps && turn.steps.length
                    ? turn.steps
                    : previous.steps,
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

        const unsubscribe = subscribeTurnStream(
            conversationId,
            turnId,
            {
                onEvent(event: AgentTurnEvent) {
                    if (closed) return;
                    switch (event.type) {
                        case "token":
                            setState((previous) => ({
                                ...previous,
                                text:
                                    previous.text +
                                    String(event.text || ""),
                            }));
                            break;
                        case "message":
                            setState((previous) => ({
                                ...previous,
                                text: String(
                                    event.text || previous.text,
                                ),
                            }));
                            break;
                        case "step.start":
                            setState((previous) => {
                                const stepId = String(
                                    event.step_id ||
                                        `step-${previous.steps.length}`,
                                );
                                if (
                                    previous.steps.some(
                                        (step) => step.id === stepId,
                                    )
                                ) {
                                    return previous;
                                }
                                const step: TurnStep = {
                                    id: stepId,
                                    turn_id: turnId,
                                    seq: previous.steps.length + 1,
                                    kind: "tool",
                                    tool_name: String(event.tool || ""),
                                    arguments: {},
                                    result: {},
                                    summary: String(
                                        event.args_preview || "",
                                    ),
                                    status: "running",
                                    error: "",
                                    duration_ms: 0,
                                    created_at: Date.now() / 1000,
                                };
                                return {
                                    ...previous,
                                    steps: [...previous.steps, step],
                                };
                            });
                            break;
                        case "step.done":
                            setState((previous) => ({
                                ...previous,
                                steps: previous.steps.map((step) =>
                                    step.id === event.step_id
                                        ? {
                                              ...step,
                                              status: event.ok
                                                  ? "ok"
                                                  : "failed",
                                              duration_ms: Number(
                                                  event.duration_ms || 0,
                                              ),
                                              summary: String(
                                                  event.summary ||
                                                      step.summary,
                                              ),
                                              error: event.ok
                                                  ? ""
                                                  : step.error,
                                          }
                                        : step,
                                ),
                            }));
                            break;
                        case "entity":
                            if (event.entity) {
                                const entity =
                                    event.entity as AgentTurn["created_entities"][number];
                                setState((previous) =>
                                    hasEntity(previous.entities, entity)
                                        ? previous
                                        : {
                                              ...previous,
                                              entities: [
                                                  ...previous.entities,
                                                  entity,
                                              ],
                                          },
                                );
                            }
                            break;
                        case "proposal":
                            if (event.proposal) {
                                const proposal =
                                    event.proposal as Record<
                                        string,
                                        unknown
                                    >;
                                setState((previous) => ({
                                    ...previous,
                                    proposals: [
                                        ...previous.proposals,
                                        proposal,
                                    ],
                                }));
                            }
                            break;
                        case "error":
                            if (!event.recoverable) {
                                setState((previous) => ({
                                    ...previous,
                                    status: "failed",
                                }));
                            }
                            break;
                        case "done":
                            stopPolling();
                            setState((previous) => ({
                                ...previous,
                                status: event.failed
                                    ? "failed"
                                    : event.canceled
                                      ? "canceled"
                                      : "succeeded",
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
                                if (turn.status !== "running") {
                                    stopPolling();
                                }
                            })
                            .catch(() => {});
                    }, 2000);
                },
            },
        );

        return () => {
            closed = true;
            stopPolling();
            unsubscribe();
        };
    }, [applyTurn, conversationId, turnId]);

    return state;
}
