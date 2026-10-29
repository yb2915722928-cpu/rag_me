# 统一输出与切分交接验证

日期：2026-10-29。规格：[Issue #45](https://github.com/yb2915722928-cpu/rag_me/issues/45)；实现：[PR #52](https://github.com/yb2915722928-cpu/rag_me/pull/52)。

## 验证边界

真实上游解析结果 → 公开交接入口 → UTF-8 JSON 导出回读。复用既有固定文件、真实格式解析器与本地 HTTP 服务；托管文档和多模态的请求发生在生成原生结果时，交接不再调用服务。测试不复制业务转换逻辑，不 mock 内部适配器。

本次验证止于交给下游的正文、结构、来源与处理状态，不代表实际切块、检索或完整 RAG 链路已运行，也不将本地服务固定响应当成云端模型质量证据。

## 回归结果

```text
python -m unittest discover -s tests -p "test_handoff_*.py" -v
python -m unittest discover -s tests -v
```

实现前 main 基线 3c23d7e：323 项，OK (skipped=10)。六项适配合入后，49 项交接测试通过；全仓 372 项，68.197 秒，OK (skipped=10)。评审修复合入 284e663 后的最终回归：372 项，65.619 秒，OK (skipped=10)，即 362 项通过、10 项跳过。

10 项是既有显式开关控制的真实远端服务验收，本轮没有启用，不将跳过视为真实云端质量通过。本机完整日志：[基线](/C:/Users/29157/.codex/tmp/rag-me-handoff-45/baseline-tests.log:1)、[最终回归](/C:/Users/29157/.codex/tmp/rag-me-handoff-45/final-regression.log:1)。

| 任务 | 新增行为测试 | 验证重点 |
| --- | --- | --- |
| 文本与网页 #46 | 7 | 完整正文、来源与 MHTML 选中部分、身份未知、诊断、失败导出、入口约束和 I/O |
| PDF/DOCX/托管文档 #47 | 7 | 页序、章节、真实字符区间、完整正文、服务结构与对齐限制、失败及待核验 |
| 表格 #48 | 11 | 行列对应、共同上下文、原值和公式缓存、多表来源、日期／时间／持续时间 JSON 表示 |
| PPTX/JSON/XML #49 | 6 | 精确正文区间、非文本对象、节点父路径、原结构、待核验与输入投影独立 |
| 图片与音视频 #50 | 9 | 任务与生成上下文、原图映射、实际时间范围、无文字／无法确认／失败和未知说话人 |
| ZIP #51 | 9 | 独立成员、同名条目、失败／忽略／未处理、部分成功、跨成员标识唯一及来源关联 |

每项实施先对尚不支持的真实行为运行失败测试，再补最小适配使其通过。后续自然支持的组合覆盖直接为绿，没有为制造红灯增加特殊分支。评审阶段的保行为重构复用现有测试，不新增镜像实现测试。

## 运行实例

README 示例输入为“普通商品签收后7天内，未拆封可退。”，来源为“售后政策.txt”，业务标识 policy-001、版本 2026-09。实际交接并回读 JSON 后，完整句子、业务身份和文档级来源保留，body_span 为空，未虚构原文件字符位置或页码。

另通过四份既有真实文件进行独立回读检查：

| 文件 | 状态 | 内容单元／来源数量 |
| --- | --- | --- |
| [TXT 样本](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/tests/testFile/txt_utf8_layout.txt) | success | 1／1 |
| [DOCX 样本](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/tests/testFile/docx_sections.docx) | success | 13／14 |
| [XLSX 样本](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/tests/testFile/xlsx_values.xlsx) | success | 31／32 |
| [JSON 样本](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/tests/testFile/json_types.json) | success | 31／32 |

检查完整原正文一致、未知业务标识和版本为空、报告内标识唯一、来源／父节点／诊断引用可解析；已有精确区间的单元文字与原正文切片一致。表格与结构化节点保留各自来源含义，不推测字符对齐。

## Standards

以 main 提交 3c23d7e 为固定基线，独立审查 c6898ec 的全部新增生产文件、六组交接测试及文档，核对仓库约定、领域术语、架构决策和用户全局规则。硬性规范违反：0。

发现 1 项 P3 启发式建议：文本、表格、结构化文档和原生／托管文档重复普通字符串警告、错误的诊断映射；这些分支的诊断代码、顺序和引用策略相同。已在 52d1d1c 将原有帮助函数移到共享的 [diagnostics.py](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/diagnostics.py:4)，各格式专属待核验事项继续自行追加。没有新增抽象层、输入校验或 schema。

修复前、修复后及与集成分支同步后，49 项公开交接测试均通过；最终全仓回归也通过。原 P3 已解决，无未处理的编码约定发现。

## Spec

同一固定基线独立对照规格 #45 和任务 #46–#51：0 项发现，最严重问题为无。

未发现可由真实上游结果触发的需求遗漏、部分实现、范围扩展或错误实现。评审核查完整正文与来源区间、未对齐结构、表格列值和公式缓存、派生文字与处理状态、无新增 API 调用，以及 ZIP 成员边界、同名条目、共享 ID 和业务身份隔离。上游失败会撤回正文或片段，没有将手工构造的非法结果组合视为缺陷。

评审汇总：Standards 硬性 0、启发式 1（P3，已解决）；Spec 0，严重项无。

## 保留的能力边界

未知业务版本不补造，内部标识只在本次报告有效。PDF 页序、DOCX 正文块、表格行列、服务块与媒体片段保持实际含义。技术处理完成和待核验状态独立，缺少待核验项也不代表内容已核验。上游已经遗漏的信息不会由交接或扩大块恢复。
