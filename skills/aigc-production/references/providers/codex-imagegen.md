# Codex ImageGen

用于 Codex 对话内的图片生成、多参考图编辑和局部修改。它是生成执行器，不能替代生产规格和 QA。

## 执行合同

1. 先通过 `preflight`，再把编译后的逐图 prompt 交给 ImageGen。
2. 新图不携带参考图参数。编辑现有图片时，只包含当前 asset 合同中的必要参考图。
3. 本地参考图先经过 `prepare-reference`。若还未查看本地目标图，先做安全预览和视觉检查。
4. 生成结果先保存到任务目录外部临时位置或 `candidates/`，再用 `register-candidate` 登记。
5. 不能在 Python CLI 中伪造“调用 Codex ImageGen API”。CLI 只登记结果和执行门禁。

官方能力说明：https://learn.chatgpt.com/docs/image-generation
