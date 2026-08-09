from typing import Any


def seed_workflows(uow) -> int:
    if uow.workflows.list():
        return 0
    defaults: list[dict[str, Any]] = [
        {
            "name": "自由创作：结构生成",
            "description": "从 Brief 与项目 Bible 生成任意结构的故事图/内容图。",
            "definition": {
                "version": "1",
                "entry_nodes": ["structure"],
                "nodes": {
                    "structure": {
                        "key": "structure",
                        "label": "内容结构",
                        "kind": "llm",
                        "inputs": ["brief", "bible"],
                        "outputs": ["story_graph"],
                        "required_capability": "llm",
                        "schema_id": "open/story_graph@1",
                        "prompt": "根据 Brief 和 Bible 生成内容结构。不要假设集数、时长或内容类型；单元数量与层级由用户意图决定。",
                    }
                },
                "edges": [],
                "global_parameters": {"temperature": 0.7},
            },
        },
        {
            "name": "自由创作：镜头规划",
            "description": "将内容结构转换成镜头计划，不固定视频类型或分镜模板。",
            "definition": {
                "version": "1",
                "entry_nodes": ["shots"],
                "nodes": {
                    "shots": {
                        "key": "shots",
                        "label": "镜头计划",
                        "kind": "llm",
                        "inputs": ["story_graph", "bible"],
                        "outputs": ["shot_plan"],
                        "required_capability": "llm",
                        "schema_id": "open/shot_plan@1",
                        "prompt": "把内容单元转换为镜头计划。镜头数量、时长策略、画面与声音构成完全由内容决定。",
                    }
                },
                "edges": [],
                "global_parameters": {"temperature": 0.6},
            },
        },
        {
            "name": "自由创作：剪辑规划",
            "description": "根据镜头、资产和音频生成剪辑决策。",
            "definition": {
                "version": "1",
                "entry_nodes": ["edit"],
                "nodes": {
                    "edit": {
                        "key": "edit",
                        "label": "剪辑规划",
                        "kind": "llm",
                        "inputs": ["shot_plan", "assets", "audio"],
                        "outputs": ["edit_plan"],
                        "required_capability": "llm",
                        "schema_id": "open/edit_plan@1",
                        "prompt": "根据镜头计划与资产生成剪辑决策。转场、节奏、音画配合由内容驱动，不要使用固定停顿或固定模板。",
                    }
                },
                "edges": [],
                "global_parameters": {"temperature": 0.5},
            },
        },
    ]
    for workflow in defaults:
        uow.workflows.create(workflow)
    return len(defaults)
