"""异步媒体 provider 协议与同步适配器包装。

真实视频 API 基本都是 提交 → 轮询 → 下载，各家字段不同。
T2.5 这里先实现协议层 + 现有 grok2api/openai 同步分支的包装；
未知 adapter 需要目标服务文档后补适配器。
"""

from typing import Any, Protocol


class MediaProviderError(RuntimeError):
    pass


class MediaProvider(Protocol):
    def submit(self, prompt: str, params: dict[str, Any]) -> str: ...
    def poll(self, task_id: str) -> tuple[str, float]: ...
    def fetch(self, task_id: str) -> bytes: ...


class SyncProviderAdapter:
    """把现有同步实现包装成异步协议：submit 直接调用并缓存结果。"""

    def __init__(self, provider: dict[str, Any], capability: str):
        from .client import generate_image, generate_video

        self.provider = provider
        self.capability = capability
        self._generate = generate_image if capability == "image" else generate_video
        self._cache: dict[str, bytes] = {}
        self._counter = 0

    def submit(self, prompt: str, params: dict[str, Any]) -> str:
        self._counter += 1
        task_id = f"sync-{self.capability}-{self._counter}"
        model = params.get("model")
        data = self._generate(self.provider, prompt, params, model=model)
        self._cache[task_id] = data
        return task_id

    def poll(self, task_id: str) -> tuple[str, float]:
        if task_id in self._cache:
            return "done", 1.0
        return "pending", 0.0

    def fetch(self, task_id: str) -> bytes:
        if task_id not in self._cache:
            raise MediaProviderError(f"unknown task: {task_id}")
        return self._cache.pop(task_id)


_SYNC_ADAPTERS = {"grok2api", "openai"}


def build_media_provider(provider: dict[str, Any], capability: str | None = None) -> MediaProvider:
    adapter = str(provider.get("adapter") or "openai").lower()
    capability = str(capability or provider.get("capability_type") or "image")
    if adapter in _SYNC_ADAPTERS:
        return SyncProviderAdapter(provider, capability)
    raise MediaProviderError(
        f"媒体渠道 {adapter} 尚未实现异步适配器（需要目标服务的接口文档：提交/轮询/下载字段）。"
    )
