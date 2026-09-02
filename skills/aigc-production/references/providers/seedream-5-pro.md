# Seedream 5.0 Pro

默认模型 ID 为 `doubao-seedream-5-0-pro-260628`，可以用 `SEEDREAM_MODEL` 覆盖。默认端点来自 `VOLCENGINE_BASE_URL`，密钥只读 `ARK_API_KEY`。

## 多参考图

prompt 必须明确每张图的角色。底图通常负责身份、商品或服装、颜色、构图和光影；姿势图只负责动作与神态。禁止复制姿势图的人物、服装、文字、Logo、水印或背景。

## 局部编辑

Seedream 路径不发送 multipart mask。使用归一化 0–999 坐标 `<point>x y</point>`、`<bbox>x1 y1 x2 y2</bbox>`，或带圈选、箭头、涂鸦的参考图。prompt 要求移除标记并自然融入，同时声明保护对象。

同类缺陷最多定向处理两次。仍未通过时，从最近已知正确底图切换 GPT Image 2，不把失败输出当正向真值。

运行前查看火山方舟最新官方文档，确认模型 ID、尺寸和计费是否变化。
