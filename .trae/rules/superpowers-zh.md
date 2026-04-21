---
alwaysApply: true
---

# Superpowers-ZH 中文增强版

你已加载 superpowers-zh 技能框架。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 高频 Skills

| Skill | 触发条件 |
|-------|---------|
| brainstorming | 创建功能、构建组件、添加功能或修改行为前 |
| chinese-commit-conventions | 自动提交时使用 |
| chinese-code-review | 代码审查 |
| systematic-debugging | 遇到 bug、测试失败或异常行为时 |
| verification-before-completion | 宣称完成前必须验证 |
| writing-plans | 多步骤任务，动手写代码前 |
| executing-plans | 执行书面实现计划时 |
| requesting-code-review | 完成任务、合并前验证 |

## 如何使用

当任务匹配某个 skill 的触发条件时，读取对应的 `.trae/skills/<skill-name>/SKILL.md` 并严格遵循其流程。

其他 skill（test-driven-development、dispatching-parallel-agents 等）按需调用，完整列表见 Skill 工具的 available_skills。
