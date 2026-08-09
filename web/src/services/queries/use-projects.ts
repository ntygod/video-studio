"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    createProject,
    deleteProject,
    getProject,
    listProjects,
    updateProject,
    type Project,
    type ProjectCreateInput,
    type ProjectDetail,
} from "@/services/api";
import { qk } from "@/services/queries/keys";

export function useProjects() {
    return useQuery({ queryKey: qk.projects(), queryFn: listProjects });
}

export function useProject(projectId: string) {
    return useQuery({
        queryKey: qk.project(projectId),
        queryFn: () => getProject(projectId),
        enabled: Boolean(projectId),
    });
}

export function useCreateProject() {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (input: ProjectCreateInput) => createProject(input),
        onSuccess: () => client.invalidateQueries({ queryKey: qk.projects() }),
    });
}

/**
 * 更新项目。
 * <p>
 * 后端是乐观锁，expected_revision 由调用方从缓存里的项目对象取。冲突（409）时
 * 主动作废项目缓存，让调用方拿到最新 revision 后重试。
 */
export function useUpdateProject(projectId: string) {
    const client = useQueryClient();
    return useMutation({
        mutationFn: ({ expectedRevision, patch }: { expectedRevision: number; patch: Partial<Project> }) =>
            updateProject(projectId, expectedRevision, patch),
        onSuccess: (project) => {
            client.setQueryData<ProjectDetail>(qk.project(projectId), (current) =>
                current ? { ...current, ...project } : current,
            );
            client.invalidateQueries({ queryKey: qk.projects() });
        },
        onError: () => {
            client.invalidateQueries({ queryKey: qk.project(projectId) });
        },
    });
}

export function useDeleteProject() {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (projectId: string) => deleteProject(projectId),
        onMutate: async (projectId) => {
            await client.cancelQueries({ queryKey: qk.projects() });
            const previous = client.getQueryData<Project[]>(qk.projects());
            client.setQueryData<Project[]>(qk.projects(), (items) =>
                (items || []).filter((item) => item.id !== projectId),
            );
            return { previous };
        },
        onError: (_error, _projectId, context) => {
            if (context?.previous) client.setQueryData(qk.projects(), context.previous);
        },
        onSettled: () => client.invalidateQueries({ queryKey: qk.projects() }),
    });
}
