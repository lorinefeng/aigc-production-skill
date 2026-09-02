# 参考图角色合同

一张参考图只能转移合同允许的事实。不要用“参考整体感觉”这种无法验收的描述。

## 每张参考图必须记录

- `role`：身份、商品结构、服装结构、颜色材质、姿势、表情、构图镜头、背景光线、风格、文字、编辑目标或负面示例。
- `authority`：`primary` 是唯一真值，`secondary` 只补充局部，`context_only` 只提供环境，`negative` 只说明禁区。
- `confidence`：primary 必须为 high。低置信度事实不能升级为不变量。
- `evidence_region`：写出证据在图中哪里，例如“画面左下商品正面标签”。
- `allowed_transfer`：允许复制的最小事实集合。
- `forbidden_transfer`：人物、服装、背景、文字、Logo、水印、道具等明确禁区。

## 冲突处理

同一事实出现冲突时，按 `primary > secondary > context_only` 处理。若两个 primary 冲突，把问题写入 `blocking_unknowns` 并暂停。不能通过选一张“看起来更合理”的图自行解决。

## 参考图进入模型前

保留原图到 `reference_sources/`。用 `prepare-reference` 生成 `reference_inputs/`，不得覆盖原图。视觉工具每轮控制图片数量和总负载，必要时先做联系表或局部裁剪。
