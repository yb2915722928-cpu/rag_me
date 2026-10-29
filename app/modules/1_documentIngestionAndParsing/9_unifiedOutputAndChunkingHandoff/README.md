# 统一输出与切分交接

接收第2–8节已经生成的原生解析结果，返回保留完整正文、交接内容单元、结构、真实来源和诊断的统一报告，支持 UTF-8 JSON 导出。本模块不读取或重新解析原文件，不调用模型，也不执行切块算法。[规格 #45](https://github.com/yb2915722928-cpu/rag_me/issues/45)定义了范围与验收边界。

```python
from importlib import import_module

text_web = import_module("app.modules.1_documentIngestionAndParsing.2_textAndWebContent")
handoff = import_module("app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff")

native = text_web.convert_bytes(
    "普通商品签收后7天内，未拆封可退。".encode("utf-8"),
    format="txt", source="售后政策.txt",
)
report = handoff.adapt_result(native, business_id="policy-001", version="2026-09")
handoff.export_json(report, "handoff.json")
document = report.documents[0]
print(document.body, document.units, document.sources, document.diagnostics)
```

## 结果约定

一份报告包含零到多份独立文档。每份文档的 body 保存完整原正文，body_format 区分 Markdown 与普通派生文字；units 是交给后续处理的内容单位，不能直接当作已经完成的最终检索块。sources 给出实际来源，diagnostics 与正文分开，structure 和 metadata 保留原生结构与上下文。

business_id 和 version 由调用方在已知时传入，未知为 None；非空值原样保留，文件名、摘要或条目序号不会自动成为业务身份。参数只接受非空白字符串或 None：类型错误抛 TypeError，空白值抛 ValueError，未知结果类型抛 TypeError。报告内部的文档、来源和单元 ID 只保证本次结果唯一，不用于跨次解析或版本匹配。

有真实正文字符映射时，body_span 使用完整 body 上的 Python 字符半开区间，alignment 为 exact。文档级内容使用 document；无字符对齐的结构使用 unmapped，body_span 保持 None。原正文单独完整保留，不能通过直接串接所有单元还原，因为单元还可能表示表格行或不带正文的结构。

| 原生结果 | 交接时保留的实际粒度 |
| --- | --- |
| TXT、Markdown、HTML、MHTML、旧文本入口 JSON | 整篇正文、编码和文档来源；MHTML 实际选中部分，不猜章节或页码 |
| PDF、DOCX | 已有正文区间、PDF 页序、提取方式或 DOCX 章节、正文块类型与顺序 |
| 托管文档 | 原 Markdown、服务结构及来源；结构与 Markdown 未建立字符映射时明确保留该限制 |
| CSV、XLSX | 已有按行文字、完整表头、共同上下文、表／行／单元格与原位置、公式及缓存，不重算 |
| PPTX、JSON、XML | 演示页、对象、备注、待核验关系，或节点类型及父子路径；非文本对象也保留来源 |
| 图片 | 识字／描述／视觉理解任务、问题、派生文字状态、模型及提示词、版本与原图映射 |
| 音视频 | 语音／画面片段、实际时间范围及精度、未知说话人、原媒体版本及待核验状态 |
| ZIP | 各成员独立文档、容器／路径／条目序号，失败／忽略／未处理及整包部分成功 |

PDF 页序不是印刷页码，DOCX 正文块号不是页码，Office 服务页不是原生演示页或单元格。节点路径、行列位置与服务块不能通过搜索正文猜成字符偏移。媒体片段范围也不代表逐句或逐词的精确时间。

## 状态与导出

status 保留真实处理状态；requires_review 与技术处理完成独立，False 也不表示内容已核验。正常空文字、无法确认、失败与 ZIP 部分成功保持可区分。失败文档 body 为 None、units 为空，来源和诊断仍可检查。ZIP 成功成员保留独立边界，同名条目由原 entry_index 区分，容器业务身份不自动复制给成员。

export_json 返回 Path，保留中文及 null，不附 BOM；失败或不完整报告也可以导出。日期与时间类原生值使用明确 ISO 表示，普通 JSON 标量不改变类型。写入错误按普通 I/O 错误传播，不自动创建父目录。适配和导出均不修改原生输入，也不为上游已经遗漏的条件补造证据。

公开入口和模型分别见 [__init__.py](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/__init__.py)与 [models.py](/C:/Users/29157/.codex/worktrees/unified-output-handoff/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/models.py)。

## 验证

```text
python -m unittest discover -s tests -p "test_handoff_*.py" -v
python -m unittest discover -s tests -v
```

测试边界为真实上游解析结果 → 公开交接入口 → JSON 导出回读，使用既有固定样本和本地 HTTP 服务。核验关键条件与来源关系、未知信息没有被补造、处理状态没有被升级，以及调用前后原生输入不变；纯交接不重复执行云端模型质量验收。
