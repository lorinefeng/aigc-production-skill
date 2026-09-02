# GPT Image 2

默认模型为 `gpt-image-2`，可用 `OPENAI_IMAGE_MODEL` 覆盖。默认端点是 OpenAI API，密钥只读 `OPENAI_API_KEY`。

## 使用方式

- 无参考图时使用 image generations。
- 有参考图或 mask 时使用 image edits。
- 参考图继续受角色合同约束；高保真输入不能代替“不许改”的明确文本。
- mask 只控制目标区域，prompt 仍要声明相邻结构、材质、文字和光影必须保持不变。
- 编辑结果只进入候选目录，视觉 QA 后才能晋级。

官方模型页：https://developers.openai.com/api/docs/models/gpt-image-2

官方图片生成指南：https://developers.openai.com/api/docs/guides/image-generation
