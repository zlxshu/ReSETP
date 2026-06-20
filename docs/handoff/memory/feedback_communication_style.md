---
name: feedback-communication-style
description: "How Claude must communicate with this user — plain language for chat, precise actionable plans for Codex prompts"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b15f032d-1e9c-453d-9aec-ea78a95aeb3f
---

与用户对话必须通俗易懂，不能用黑话、缩写、代称等增加理解负担的词语。

**Why:** 用户明确要求，违反会造成沟通障碍。

**How to apply:** 所有与用户的对话用普通人能看懂的中文，解释清楚每个决定背后的原因，不假设用户知道某个术语。

---

给Codex的提示词必须满足以下标准：
1. 精准——有具体文件路径、函数名、数字，不含模糊描述
2. 合规——符合OpenAI Codex使用规范
3. 强执行力——相当于详细施工方案，Codex按步骤做就能完成，不需要猜
4. 有边界——明确写清楚"不做什么"，防止Codex超范围改动
5. 实事求是——只写已确认的事实，不猜测、不夸大、不编造预期结果

**Why:** 用户要求Codex提示词"几乎就是详细的施工方案"，过于模糊或过度承诺的提示词会导致Codex输出无法用。

**How to apply:** 写提示词前先读相关代码确认事实，每条步骤都写明"在哪个文件的哪里改什么"，边界条件和失败退出条件也要写清楚。
