# aigc-production-skill

把商业生图请求整理成可验证、可选择性返工、可直接交付的生产任务。

这个项目包含两部分：一个面向 Codex 的渐进式 Skill，以及一套可二次开发的 Python CLI。它不替代底层生图模型。Codex ImageGen、Seedream 5.0 Pro 和 GPT Image 2 都只是执行路径，任务事实、参考图边界、QA 和交付规则由用户自己掌握。

> **English summary** — A Codex-first, production-oriented image workflow. It turns references and client feedback into an auditable job spec, routes work to Codex ImageGen, Seedream, or GPT Image 2, records candidates and reviews, reruns only failed assets, and keeps the final delivery directory clean. The Python CLI can also be reused outside Codex.

## 它解决什么

- 一张姿势参考把错误服装、人物或背景带进最终图。
- 为修一只手整图重绘，已经正确的脸、商品或材质又漂了。
- 批量任务没有校准图，同一种错误一次扩散到整套。
- 候选、失败版本、蒙版和最终 PNG 混在一个目录。
- 内部技术检查被误写成客户批准。

核心规则很简单：没有生产规格不开始生成；参考图必须写清允许和禁止迁移的内容；不确定按失败处理；只重跑失败资产；`generated/` 只保留最终交付文件。

## 安装

需要 Python 3.11 或更高版本。推荐使用 `uv`。

```bash
git clone https://github.com/lorinefeng/aigc-production-skill.git
cd aigc-production-skill
uv sync --extra dev
uv run aigc-production doctor
```

把 Skill 链接到 Codex：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$PWD/skills/aigc-production" "${CODEX_HOME:-$HOME/.codex}/skills/aigc-production"
```

重启 Codex 或创建新任务后，可以直接说：

```text
Use $aigc-production to turn these product references and image requirements into a production job.
```

## 配置模型 API

复制 `.env.example` 为 `.env`，只在本机填写需要使用的密钥。不要把密钥发到聊天、任务规格或 issue。

```dotenv
ARK_API_KEY=
OPENAI_API_KEY=
```

- 不配置 API Key 时，Codex 仍可使用内置 ImageGen，所有离线规格和门禁也可运行。
- 配置 `ARK_API_KEY` 后可调用 Seedream 5.0 Pro。
- 配置 `OPENAI_API_KEY` 后可调用 GPT Image 2。
- `VOLCENGINE_BASE_URL` 和 `OPENAI_BASE_URL` 可以覆盖，但默认只指向官方端点。

## 最短工作流

```bash
uv run aigc-production init ./jobs/demo --scenario product-new-image
# 编辑 jobs/demo/production_spec.json 并放入真实参考图
uv run aigc-production prepare-reference ./jobs/demo/reference_sources/product.jpg ./jobs/demo/reference_inputs/product.jpg
uv run aigc-production preflight ./jobs/demo/production_spec.json
uv run aigc-production compile ./jobs/demo/production_spec.json 01 --output ./jobs/demo/prompts/01.txt
uv run aigc-production run ./jobs/demo/production_spec.json 01 --provider seedream
```

候选需要经过视觉检查：

```bash
uv run aigc-production review ./jobs/demo/production_spec.json 01 candidates/01__example.png pass
uv run aigc-production promote ./jobs/demo/production_spec.json 01 candidates/01__example.png
uv run aigc-production delivery ./jobs/demo/production_spec.json
```

Codex ImageGen 生成的文件用 `register-candidate` 登记，再走同一套 review、promote 和 delivery。

## CLI

| 命令 | 作用 |
| --- | --- |
| `doctor` | 检查依赖、API Key 是否存在和可用 provider，不显示密钥 |
| `init` | 建立任务目录和通用生产规格 |
| `prepare-reference` | 生成长边和文件大小受控的模型输入，不覆盖原图 |
| `preflight` | 检查参考图角色、不变量、QA、批量校准和交付目录 |
| `compile` | 从唯一规格源编译逐图 prompt |
| `run` | 调用 Seedream 或 GPT Image 2，只写入候选目录 |
| `register-candidate` | 登记 Codex ImageGen 或其他外部工具生成的候选 |
| `review` | 记录 pass、fail 或 uncertain；uncertain 不能晋级 |
| `promote` | 只把已通过候选复制到 `generated/` |
| `delivery` | 校验最终数量、命名、真实格式和 QA 记录 |

## 渐进式场景经验

Skill 会按任务只读取需要的场景和 provider 文档：

- 商品新图
- 人物与服装一致性
- 精确局部修复
- 批量套图与干净交付

v0.1 正式验证 Codex。其他 Agent 可以复用 Python CLI，但本项目暂不承诺它们的 Skill 安装兼容性。

## 二次开发

新增模型只需要实现 `ImageProvider`：接收 `ImageRequest`，返回不含密钥的 `ProviderResult`。任务规格、prompt 编译、候选登记、QA 和交付门禁不依赖具体模型。

```python
from aigc_production.providers.base import ImageProvider, ImageRequest, ProviderResult
```

测试使用合成图片和 HTTP Mock，不包含真实客户素材、Logo、SKU、订单或私有域名。

## 已知限制

- 自动文件门禁不能代替人物、手指、服装、商品结构和审美的视觉验收。
- 模型仍可能产生幻觉，Skill 负责限制错误扩散并留下可恢复记录，不保证一次生成通过。
- v0.1 只覆盖商业静态图片，不包含图生视频或视频分镜。
- API 定价和模型能力会变化，运行前请查看提供商官方文档。

## License

[MIT](LICENSE)

