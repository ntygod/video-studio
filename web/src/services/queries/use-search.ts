"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { searchProject } from "@/services/api";
import { qk } from "@/services/queries/keys";

/** 防抖 FTS 搜索（T3.F2）：输入停 250ms 后才发请求。 */
export function useSearch(projectId: string, query: string, type = "all") {
    const [debounced, setDebounced] = useState(query.trim());
    useEffect(() => {
        const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
        return () => window.clearTimeout(timer);
    }, [query]);

    return useQuery({
        queryKey: [...qk.search(projectId), type, debounced],
        queryFn: () => searchProject(projectId, debounced, type),
        enabled: Boolean(projectId) && debounced.length > 0,
    });
}
