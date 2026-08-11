"use client";

import { get } from "./http";
import type { HealthStatus } from "./types";

export function checkHealth() {
    return get<HealthStatus>("/api/health");
}
