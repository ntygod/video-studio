"use client";

import { useState } from "react";

import { ArtifactPanel } from "@/features/canvas/components/artifact-panel";
import { GettingStartedPanel } from "@/features/canvas/components/getting-started-panel";
import { ProposalList } from "@/features/canvas/components/proposal-list";
import { UnitCreateModal } from "@/features/structure/components/unit-create-modal";
import { useWorkspaceData } from "@/features/workspace/hooks/use-workspace-data";
import { useWorkspaceRoute } from "@/features/workspace/hooks/use-workspace-route";
import { Text } from "@/shared/ui";

/** 画布 · 故事：待处理建议、下一步引导、创作稿件。 */
export function StoryView() {
    const { projectId, contentArtifacts, pendingProposals, project, units, unitOptions } = useWorkspaceData();
    const { selectedUnitId, setSelectedUnit } = useWorkspaceRoute();
    const [createUnitOpen, setCreateUnitOpen] = useState(false);
    return (
        <div className="mx-auto w-full max-w-[1120px] space-y-4 px-5 py-6 md:px-7">
            <div>
                <Text as="h1" variant="heading" tone="ink">
                    稿件与结构
                </Text>
                <Text as="p" variant="caption" tone="muted" className="mt-1 leading-5">
                    审阅当前单元的内容稿件；AI 对已有内容的修改会以可逐条采纳的提案出现。
                </Text>
            </div>
            <ProposalList projectId={projectId} proposals={pendingProposals} />
            {contentArtifacts.length === 0 ? <GettingStartedPanel onCreateUnit={() => setCreateUnitOpen(true)} /> : null}
            <ArtifactPanel projectId={projectId} artifacts={contentArtifacts} />

            <UnitCreateModal open={createUnitOpen} projectId={projectId} unitOptions={unitOptions} defaultParentId={selectedUnitId} orderIndex={units.length || 0} onClose={() => setCreateUnitOpen(false)} onCreated={setSelectedUnit} />
        </div>
    );
}
