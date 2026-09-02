# 批量套图与干净交付

每个资产有独立 ID、目标文件名、参考绑定、不变量、动作、镜头、变化范围和验收项。共享事实写入全局不变量，逐图差异留在 asset 内。

## 批量规则

- 先校准一张，再分批生成。
- manifest 记录 provider、模型、请求标识、候选哈希和用量；不记录密钥。
- 失败只回到对应 asset，已通过项不重跑。
- 候选放在 `candidates/`，失败版本移到 `supporting_files/rejected_versions/`。
- `generated/` 中不允许出现 TIFF、CMYK 辅助文件、prompt、mask、manifest、联系表、备份或 `v2` 候选。

运行 `delivery` 检查数量、精确文件名、扩展名、真实图片格式、内部 QA 与晋级哈希。客户批准另行记录，不因内部通过自动变为 true。
