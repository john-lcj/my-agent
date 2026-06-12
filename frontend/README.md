# frontend(留白)

薄聊天界面,最后阶段再做。重点不在炫,而在:**流式输出 + 可中断 + 确认卡片**。

计划:单页应用(或先用最简 HTML),通过 WebSocket/SSE 连到 `server/app.py`,
渲染 `core.types.Event` 事件流;遇到 `APPROVAL_REQUEST` 时弹确认卡片。

当前阶段请用 CLI:在项目根运行 `python main.py`。
