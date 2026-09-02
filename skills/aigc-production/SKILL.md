---
name: aigc-production
description: Turn commercial image-generation or image-editing requests into an auditable production workflow with fact extraction, reference-role contracts, model routing, candidate review, selective reruns, and clean final delivery. Use for product images, model or wardrobe consistency, precise local edits, multi-image batches, or any task where generated images must preserve real reference details and pass delivery gates.
license: MIT
---

# AIGC Production

把生图模型当作执行器。生产规格是唯一事实源，候选、审核、返工和最终交付必须可追溯。

## 总流程

1. 读取需求和全部参考资料，先写事实清单。把缺失或冲突事实放入 `blocking_unknowns`；未清零前停止生成。
2. 为每张参考图签角色合同，记录权威级别、证据区域、允许迁移和禁止迁移的内容。详见 [reference-contracts.md](references/reference-contracts.md)。
3. 使用 `aigc-production init` 建任务目录，填写 `production_spec.json`，再运行 `preflight`。
4. 批量任务先选一张高风险校准图。校准通过前不得扩散到整批。
5. 按场景和 provider 路由表只读取必要文档，编译逐图 prompt，生成结果只能进入 `candidates/`。
6. 对候选做内部视觉 QA。`uncertain` 按失败处理；只重跑失败资产，同类缺陷最多自动重跑两次。
7. 通过项用 `promote` 晋级。最终运行 `delivery`，确认 `generated/` 只包含规格中预期的最终 PNG。

## 强制底线

- 无规格不生成；无权威证据不猜关键结构、文字、Logo、数量、颜色或材质。
- 参考图必须有角色合同。姿势图不得偷渡人物身份、服装、背景、文字或水印。
- 已通过项不得重跑；失败或不确定输出不得作为正向参考。
- 局部缺陷优先局部编辑，不为修一个区域整图重绘。
- 模型返回只算候选。内部 QA 与客户批准是两个字段，不得互相代替。
- `generated/` 默认只保留验收通过、命名准确、真实格式为 PNG 的交付图。prompt、mask、manifest、失败版本和辅助格式全部留在目录外。
- API Key 只能来自环境变量。不得写入规格、日志、manifest、聊天或 Git。
- 查看图片前执行输入安全处理；长边不得超过 2048px，文件不得超过 1.5MiB。不要覆盖原图。

## 场景路由

只读取当前任务对应的一份场景文档；混合任务可以组合读取。

| 任务 | 必读场景 |
| --- | --- |
| 商品换背景、营销新图、静物组合 | [product-new-image.md](references/scenarios/product-new-image.md) |
| 同一人物、服装、饰品或造型跨图一致 | [identity-wardrobe.md](references/scenarios/identity-wardrobe.md) |
| 手指、文字、商品局部、材质或构图小范围修复 | [precise-local-edit.md](references/scenarios/precise-local-edit.md) |
| 多张套图、选择性返工、最终目录清理 | [batch-delivery.md](references/scenarios/batch-delivery.md) |

所有场景都要遵守 [qa-and-rerun.md](references/qa-and-rerun.md)。

## Provider 路由

根据实际执行路径只读取一份 provider 文档。

| 执行路径 | 何时使用 | 文档 |
| --- | --- | --- |
| Codex ImageGen | 无外部 API Key；对话内生成、多参考图或局部编辑 | [codex-imagegen.md](references/providers/codex-imagegen.md) |
| Seedream 5.0 Pro | 多参考图、组图、坐标或视觉标记式局部编辑 | [seedream-5-pro.md](references/providers/seedream-5-pro.md) |
| GPT Image 2 | 高保真参考图编辑、mask、定向修复；或 Seedream 同类缺陷两次未过 | [gpt-image-2.md](references/providers/gpt-image-2.md) |

不要把 Codex ImageGen 伪装成外部 Python API。使用工具得到图片后，执行 `register-candidate`，再走统一 QA 和交付链。

## CLI 顺序

```bash
aigc-production doctor
aigc-production init ./jobs/example --scenario product-new-image
aigc-production prepare-reference SOURCE OUTPUT
aigc-production preflight ./jobs/example/production_spec.json
aigc-production compile ./jobs/example/production_spec.json 01 --output ./jobs/example/prompts/01.txt
aigc-production run ./jobs/example/production_spec.json 01 --provider seedream
aigc-production review ./jobs/example/production_spec.json 01 candidates/CANDIDATE.png pass
aigc-production promote ./jobs/example/production_spec.json 01 candidates/CANDIDATE.png
aigc-production delivery ./jobs/example/production_spec.json
```

如果 provider 是 Codex ImageGen，用 `register-candidate` 替代 `run`。执行任何生成动作前都要先通过 `preflight`。
