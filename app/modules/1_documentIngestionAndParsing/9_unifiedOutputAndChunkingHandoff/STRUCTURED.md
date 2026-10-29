# PPTX 与 JSON/XML 交接

[公开入口](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/__init__.py) 接收第 5 节已有的原生解析结果，通过[结构适配器](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/structured.py) 生成一份独立文档。调用方式：

```python
from importlib import import_module

parsing = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
handoff = import_module(
    "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff"
)
native = parsing.convert_file("rules.json")
report = handoff.adapt_result(native, business_id="退款规则", version="第二版")
handoff.export_json(report, "handoff.json")
```

## 正文、单元与来源

- 文档正文完整保留原 Markdown，包括没有来源区间覆盖的表格标记。正文不会用单元文字重新拼接。
- 文档级来源保留输入位置与格式；每条原生内容来源各有一条来源和一个内容单元，单元引用对应来源。来源定位完整保留原生字段。
- PPTX 已有的半开字符区间直接映射到正文，单元文字为该区间内的原 Markdown，`alignment="exact"`。演示页、对象 ID 路径、名称、段落与层级、单元格行列及备注原样保留。
- 非文本对象的单元文字与正文区间为空，`alignment="unmapped"`，来源仍然存在。组合对象坐标仍为父容器内的原始坐标；对象图层顺序不代表已核验阅读顺序。PPTX 不从对象路径推导语义父单元。
- JSON/XML 不重新解析，不搜索正文猜测字符位置。每个节点单元保留原节点类型、路径和父路径，并通过真实父路径关联 `parent_id`；JSON 根路径的空字符串与无父路径区别处理。节点单元文字和正文区间为空，`alignment="unmapped"`，完整内容仍在文档正文中。
- `structure.sources` 与 `structure.review_issues` 是原生结构的独立投影，补充统一来源与单元。JSON 导出将原生坐标元组表示为数组。

## 状态与诊断

技术处理状态保留为 `success` 或 `failed`；`requires_review` 独立保留上游结论。每条待核验事项保留原代码和消息，诊断级别为 `review`，关联对应文档、来源与单元。图片、连接线、组合、图表等无文字对象也保留这些关联。

普通警告与错误分别使用 `upstream_warning`、`upstream_error`，关联文档及输入来源，不进入正文。失败结果正文为空、单元为空，仍可导出来源、编码与错误。没有待核验事项不代表质量已经通过核验。

适配器只消费已有结果，不读取原文件、不调用解析器或模型、不运行切块。业务标识与版本仅使用显式参数，未知保持空；所有对象 ID 只保证本份报告内唯一。修改交接输出不会修改原生输入。

## 本票验证

复用已有固定样本，经真实解析器、公开交接入口、UTF-8 JSON 导出回读验证；测试见[交接测试](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/tests/test_handoff_structured.py)。

```shell
python -m unittest tests.test_handoff_structured tests.test_handoff_text_web -v
```
