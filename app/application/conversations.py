"""对话应用层。

旧的一次性 send_message（全量转储项目 + chat_json）已由
app.application.agent.loop.run_turn 取代：用户消息与回合在路由层落库，
Agent 循环负责工具调用、SSE 事件与最终回复。
"""
