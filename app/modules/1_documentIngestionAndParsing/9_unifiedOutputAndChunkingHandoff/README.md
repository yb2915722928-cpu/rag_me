# 统一输出与切分交接

第46项提供文本与网页的单向交接及 UTF-8 JSON 导出。输入是第2节既有解析结果，不是文件或字节；本模块不解析文件、不调用模型、不运行切块算法。

```python
from importlib import import_module

text_web = import_module("app.modules.1_documentIngestionAndParsing.2_textAndWebContent")
handoff = import_module("app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff")

native = text_web.convert_file("notice.txt")
report = handoff.adapt_result(native, business_id=None, version=None)
handoff.export_json(report, "notice.json")
```

支持 TXT、Markdown、HTML、MHTML 和旧文本入口 JSON。每份文档保留完整 Markdown 正文、独立的来源与诊断，成功时只有一个整篇内容单元。来源不提供章节、页码或字符映射，因此单元的 alignment 为 document，body_span 为 None；MHTML 保留实际选中的部分与编码。

business_id 和 version 由调用方明确传入，未知为 None；仅接受非空白字符串或 None。错误类型抛 TypeError，空串或全空白抛 ValueError，未知结果类型抛 TypeError。内部文档、来源和单元 ID 只在本次报告内有意义，不可用作稳定业务标识。

失败保留 Document、来源与诊断，body 为 None、units 为空，仍能导出 JSON。导出返回 Path，保留中文及 null，不附 BOM；写入错误按普通 I/O 错误传播，不自动创建父目录。适配和导出均不修改原生输入。status 仅表示技术处理状态，requires_review=False 不表示质量已通过。

公共 dataclass 在 [models.py](/C:/Users/29157/.codex/worktrees/46-handoff-text-web/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/models.py)，文本适配在 [text_web.py](/C:/Users/29157/.codex/worktrees/46-handoff-text-web/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/text_web.py)，公开入口在 [__init__.py](/C:/Users/29157/.codex/worktrees/46-handoff-text-web/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/__init__.py)。后续格式在独立适配模块中接入具体类型的静态分派；IdAllocator 应在同一报告中共享。structure 与 metadata 用于保留原生结构和上下文，不能替代统一单元及其来源关系。当前仅接入第2节结果。

验证命令：

```text
python -m unittest discover -s tests -p test_handoff_text_web.py -v
python -m unittest discover -s tests -v
```

[公开边界测试](/C:/Users/29157/.codex/worktrees/46-handoff-text-web/rag-me/tests/test_handoff_text_web.py)使用既有真实解析器与固定样本，覆盖文件/字节结果、正文保真、MHTML 来源、未知/显式业务标识、诊断、失败导出、非法参数、I/O 错误和输入不变。
