"use client";

import { useState } from "react";

import { ArtifactPanel } from "@/features/canvas/components/artifact-panel";
import { GettingStartedPanel } from "@/features/canvas/components/getting-started-panel";
import { ProposalList } from "@/features/canvas/components/proposal-list";
import { UnitCreateModal } from "@/features/structure/components/unit-create-modal";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";

/** 画布 · 故事：待处理建议、下一步引导、创作稿件。 */
export function StoryView() {
    const { projectId, contentArtifacts, pendingProposals, project, unitOptions } = useWorkspaceData();
    const { selectedUnitId, setSelectedUnit } = useWorkspaceRoute();
    const [createUnitOpen, setCreateUnitOpen] = useState(false);

    return (
        <div className="mx-auto w-full max-w-[900px] space-y-5 px-5 py-6 md:px-7">
            <ProposalList projectId={projectId} proposals={pendingProposals} />
            <GettingStartedPanel onCreateUnit={() => setCreateUnitOpen(true)} />
            <ArtifactPanel projectId={projectId} artifacts={contentArtifacts} />

            <UnitCreateModal
                open={createUnitOpen}
                projectId={projectId}
                unitOptions={unitOptions}
                defaultParentId={selectedUnitId}
                orderIndex={project?.units.length || 0}
                onClose={() => setCreateUnitOpen(false)}
                onCreated={setSelectedUnit}
            />
        </div>
    );
}
