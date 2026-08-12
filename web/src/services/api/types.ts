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

export type TurnStatus = "running" | "succeeded" | "failed" | "canceled" | "reverted";

export type TurnStep = {
    id: string;
    turn_id: string;
    seq: number;
    kind: "tool" | "message" | "error";
    tool_name: string;
    arguments: Record<string, unknown>;
    result: Record<string, unknown>;
    summary: string;
    status: "running" | "ok" | "failed";
    error: string;
    duration_ms: number;
    created_at: number;
};

export type AgentTurn = {
    id: string;
    conversation_id: string;
    project_id: string;
    unit_id: string | null;
    user_message_id: string | null;
    assistant_message_id: string | null;
    status: TurnStatus;
    context_refs: Array<{ type: string; id?: string; section?: string }>;
    created_entities: Array<{ type: "artifact" | "unit" | "asset" | "job"; id: string }>;
    prompt_tokens: number;
    completion_tokens: number;
    error: string;
    created_at: number;
    updated_at: number;
    steps?: TurnStep[];
    runtime_plan_id?: string;
    runtime_status?: string;
};

export type StartTurnResult = {
    turn_id: string;
    runtime_plan_id: string;
    user_message: ConversationMessage;
};

export type AgentTurnEvent = {
    id?: string;
    seq?: number;
    type:
        | "step.start"
        | "step.done"
        | "token"
        | "message"
        | "proposal"
        | "entity"
        | "error"
        | "done";
    step_id?: string;
    tool?: string;
    args_preview?: string;
    ok?: boolean;
    duration_ms?: number;
    summary?: string;
    text?: string;
    message?: string;
    recoverable?: boolean;
    entity?: { type: string; id: string };
    proposal?: Proposal;
    message_id?: string | null;
    usage?: { prompt: number; completion: number };
    canceled?: boolean;
    failed?: boolean;
    durable?: boolean;
    [key: string]: unknown;
};

export type ProviderModel = {
    id: string;
    name: string;
    model_id: string;
    capability_type: string;
    capabilities: Record<string, unknown>;
    defaults: Record<string, unknown>;
    is_default: boolean;
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
    is_default: boolean;
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

export type Asset = {
    id: string;
    project_id: string;
    unit_id: string | null;
    shot_id: string | null;
    kind: string;
    name: string;
    uri: string;
    thumb_uri: string;
    mime_type: string;
    sha256: string;
    parent_asset_id: string | null;
    generation: Record<string, unknown>;
    metadata: Record<string, unknown>;
    created_at: number;
};

/** 分页响应：items + 不透明游标（(created_at,id) 复合）。 */
export type Page<T> = {
    items: T[];
    next_cursor: string | null;
};

/** 项目详情已瘦身（T3.1）：只回项目本身 + 统计，不再内嵌列表。 */
export type ProjectDetail = Project & {
    unit_count: number;
    artifact_count: number;
    asset_count: number;
    pending_proposal_count: number;
    last_activity: number;
};

/** 项目库列表卡片所需的聚合字段（T3.4）。 */
export type ProjectSummary = {
    id: string;
    cover_asset_id: string | null;
    cover_asset_uri: string;
    pending_proposal_count: number;
    unit_count: number;
    last_activity: number;
};

/** FTS 检索结果（T3.2）。 */
export type SearchHit = {
    type: "unit" | "artifact";
    id: string;
    title: string;
    snippet: string;
    unit_id: string | null;
};

export type HealthStatus = {
    ok: boolean;
    version: string;
    schema_version: number;
    db_ok: boolean;
    media_root_ok: boolean;
};

export type OkResult = { ok: boolean };
