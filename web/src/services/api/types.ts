/**
 * 后端领域模型的 TypeScript 映射。
 * <p>
 * 与 app/domain 下的 pydantic 模型一一对应。所有开放字段（project_type / unit_type / stage /
 * artifact kind 等）在后端都是自由文本，这里保持 string 而不收窄为联合类型。
 */

export type PlatformTarget = {
    platform: string;
    aspect_ratio: string;
    target_seconds: number;
    language: string;
};

export type CreativeBrief = {
    title: string;
    concept: string;
    objective: string;
    format_id: string;
    format_notes: string;
    audience: { description: string; age_range: string; knowledge_level: string; interests: string[] };
    platforms: PlatformTarget[];
    tone: string[];
    references: string[];
    constraints: Array<{ kind: string; value: string; required: boolean }>;
    custom_fields: Record<string, unknown>;
    approved: boolean;
};

export type CharacterBible = {
    id: string;
    name: string;
    role: string;
    personality: string;
    appearance: string;
    wardrobe: string[];
    forbidden_traits: string[];
    reference_asset_ids: string[];
    voice: Record<string, unknown>;
};

export type ProjectBible = {
    logline: string;
    themes: string[];
    long_arc: string;
    characters: CharacterBible[];
    world: { premise: string; era: string; locations: Array<Record<string, unknown>>; rules: string[] };
    style: {
        visual_direction: string;
        color_palette: string[];
        lighting: string;
        camera_language: string;
        subtitle_style: Record<string, unknown>;
        sound_direction: string;
        negative_prompts: string[];
    };
    continuity: Array<Record<string, unknown>>;
    custom_fields: Record<string, unknown>;
};

export type Project = {
    id: string;
    title: string;
    project_type: string;
    workflow_id: string;
    stage: string;
    brief: CreativeBrief;
    bible: ProjectBible;
    settings: Record<string, unknown>;
    custom_fields: Record<string, unknown>;
    revision: number;
    created_at: number;
    updated_at: number;
};

export type CreativeUnit = {
    id: string;
    project_id: string;
    parent_id: string | null;
    unit_type: string;
    order_index: number;
    title: string;
    summary: string;
    stage: string;
    continuity_summary: string;
    custom_fields: Record<string, unknown>;
    created_at: number;
    updated_at: number;
};

export type ArtifactVersionStatus = "draft" | "proposed" | "approved" | "locked";

export type ArtifactVersion = {
    id: string;
    artifact_id: string;
    version: number;
    status: ArtifactVersionStatus;
    schema_version: number;
    payload: Record<string, unknown>;
    source: string;
    parent_version_id: string | null;
    note: string;
    created_at: number;
};

export type Artifact = {
    id: string;
    project_id: string;
    unit_id: string | null;
    kind: string;
    name: string;
    schema_id: string;
    current_version_id: string | null;
    current_version?: ArtifactVersion | null;
    created_at: number;
    updated_at: number;
};

/** AI 提出的单条变更操作，形如 JSON Patch。 */
export type ProposalOperation = {
    op: string;
    path: string;
    value?: unknown;
};

export type Proposal = {
    id: string;
    project_id: string;
    unit_id: string | null;
    artifact_id: string | null;
    artifact_kind: string;
    base_version_id: string | null;
    title: string;
    rationale: string;
    operations: ProposalOperation[];
    proposed_payload: Record<string, unknown> | null;
    status: "pending" | "accepted" | "rejected";
    created_at: number;
    updated_at: number;
};

export type ConversationMessage = {
    id: string;
    conversation_id: string;
    seq: number;
    role: "user" | "assistant" | "system";
    content: string;
    proposal_ids: string[];
    created_at: number;
};

export type Conversation = {
    id: string;
    project_id: string;
    unit_id: string | null;
    title: string;
    created_at: number;
    updated_at: number;
    messages?: ConversationMessage[];
};

export type SendMessageResult = {
    user_message: ConversationMessage;
    assistant_message: ConversationMessage;
    proposals: Proposal[];
};

export type ProviderModel = {
    id: string;
    name: string;
    model_id: string;
    capability_type: string;
    capabilities: Record<string, unknown>;
    defaults: Record<string, unknown>;
};

export type ProviderProfile = {
    id: string;
    name: string;
    capability_type: string;
    adapter: string;
    base_url: string;
    api_key: string;
    enabled: boolean;
    settings: Record<string, unknown>;
    models: ProviderModel[];
    created_at: number;
    updated_at: number;
};

export type ModelCapability = {
    id: string;
    name: string;
    model_id: string;
    capability_type: string;
    capabilities: Record<string, unknown>;
    defaults: Record<string, unknown>;
    provider_profile_id: string;
    provider_name: string;
    adapter: string;
    enabled: boolean;
};

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export type Job = {
    id: string;
    project_id: string;
    unit_id: string | null;
    job_type: string;
    status: JobStatus;
    progress: number;
    cancel_requested: boolean;
    payload: Record<string, unknown>;
    result: Record<string, unknown> | null;
    error: string;
    created_at: number;
    updated_at: number;
};

export type JobEvent = {
    id: string;
    job_id: string;
    level: "info" | "warn" | "error";
    stage: string;
    message: string;
    progress: number | null;
    created_at: number;
};

export type JobDetail = Job & { events?: JobEvent[] };

export type WorkflowDefinition = {
    version?: string;
    entry_nodes?: string[];
    nodes?: Record<string, unknown>;
    edges?: Array<Record<string, unknown>>;
    global_parameters?: Record<string, unknown>;
};

export type Workflow = {
    id: string;
    name: string;
    description: string;
    version: string;
    definition: WorkflowDefinition;
    created_at: number;
    updated_at: number;
};

export type Asset = {
    id: string;
    project_id: string;
    unit_id: string | null;
    shot_id: string | null;
    kind: string;
    name: string;
    uri: string;
    mime_type: string;
    sha256: string;
    parent_asset_id: string | null;
    generation: Record<string, unknown>;
    metadata: Record<string, unknown>;
    created_at: number;
};

export type ProjectDetail = Project & {
    units: CreativeUnit[];
    artifacts: Artifact[];
    pending_proposals: Proposal[];
};

export type HealthStatus = {
    ok: boolean;
    version: string;
    schema_version: number;
    db_ok: boolean;
    media_root_ok: boolean;
};

export type OkResult = { ok: boolean };
