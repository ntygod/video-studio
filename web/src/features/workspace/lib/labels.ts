/**
 * 工作台的中文标签映射。
 * <p>
 * 后端的 kind / stage / unit_type 都是开放文本，这里只为已知值提供友好名称，
 * 未知值一律回落到通用词而不是报错——开放模型下用户随时可能创造新类型。
 */

const ARTIFACT_KIND_LABELS: Record<string, string> = {
    analysis: "内容分析",
    story_graph: "故事结构",
    outline: "内容大纲",
    script: "脚本",
    screenplay: "剧本",
    shot_plan: "分镜计划",
    edit_plan: "剪辑计划",
    timeline: "时间线",
    generated: "AI 稿件",
    brief: "项目简介",
    project_bible: "设定集",
};

const ARTIFACT_STATUS_LABELS: Record<string, string> = {
    draft: "草稿",
    proposed: "待确认",
    approved: "已确认",
    locked: "已定稿",
};

const ASSET_KIND_LABELS: Record<string, string> = {
    image: "图片",
    video: "视频",
    voice: "配音",
    audio: "音频",
    music: "音乐",
    sfx: "音效",
    reference: "参考素材",
    render: "生成视频",
};

const UNIT_KIND_LABELS: Record<string, string> = {
    unit: "内容",
    volume: "卷",
    chapter: "章节",
    episode: "分集",
    scene: "场景",
    shot: "镜头",
    section: "小节",
    task: "任务",
};

const STAGE_LABELS: Record<string, string> = {
    brief: "构思中",
    planning: "规划中",
    draft: "创作中",
    production: "制作中",
    review: "待审阅",
    final: "已完成",
    completed: "已完成",
};

const CAPABILITY_LABELS: Record<string, string> = {
    llm: "大语言模型",
    image: "图片生成",
    video: "视频生成",
    tts: "语音合成",
    audio: "音频处理",
    embedding: "向量嵌入",
    text: "文本处理",
    other: "其他能力",
};

const JOB_TYPE_LABELS: Record<string, string> = {
    render: "渲染出片",
    llm: "文本生成",
    workflow: "工作流",
    workflow_node: "工作流节点",
    voice_synthesis: "配音合成",
    storyboard: "分镜/动效",
    edit: "智能剪辑",
    tts: "配音合成",
    asset: "素材生成",
};

const JOB_STATUS_LABELS: Record<string, { label: string; color: string }> = {
    queued: { label: "排队中", color: "default" },
    running: { label: "运行中", color: "processing" },
    succeeded: { label: "已完成", color: "success" },
    failed: { label: "失败", color: "error" },
    canceled: { label: "已取消", color: "warning" },
};

/** 项目中不作为"创作稿件"展示的内部 artifact 类型。 */
export const META_ARTIFACT_KINDS = ["brief", "project_bible"];

export function artifactKindLabel(kind: string): string {
    return ARTIFACT_KIND_LABELS[kind] || "创作稿件";
}

export function artifactStatusLabel(status?: string): string {
    return ARTIFACT_STATUS_LABELS[status || ""] || "草稿";
}

export function assetKindLabel(kind: string): string {
    return ASSET_KIND_LABELS[kind] || "素材";
}

export function unitKindLabel(kind: string): string {
    return UNIT_KIND_LABELS[kind] || "内容";
}

export function stageLabel(stage: string): string {
    return STAGE_LABELS[stage.toLowerCase()] || "进行中";
}

export function capabilityLabel(capability: string): string {
    return CAPABILITY_LABELS[capability] || capability;
}

export function jobTypeLabel(type: string): string {
    return JOB_TYPE_LABELS[type] || type;
}

export function jobStatusMeta(status: string): { label: string; color: string } {
    return JOB_STATUS_LABELS[status] || JOB_STATUS_LABELS.queued;
}

/** 项目是否处于收尾/完成状态。 */
export function isCompletedStage(stage: string): boolean {
    return ["final", "completed"].includes(stage.toLowerCase());
}
