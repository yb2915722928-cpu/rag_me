# ZIP 成员交接

公开入口接收已有的 `ZipResult`，逐成员复用文本、托管文档、表格、结构化文档、图片和媒体适配器。不重新打开 ZIP、读取成员文件、解析正文或请求 HTTP 服务；同一份报告的所有适配调用共享一个 `IdAllocator`。

## 使用已有解析结果

下面的 `native` 是 ZIP 模块已经生成的原生结果：

```python
from importlib import import_module

handoff = import_module(
    "app.modules.1_documentIngestionAndParsing.unifiedDocumentHandoff"
)
report = handoff.adapt_result(native, business_id="培训资料包", version="修订二")
path = handoff.export_json(report, "handoff.json")

documents = {document.id: document for document in report.documents}
for member in report.metadata["members"]:
    member_documents = [documents[identifier] for identifier in member["document_ids"]]
    print(member["source"], member["status"], member_documents)
```

`business_id` 和 `version` 只写入容器记录；成员文档的这两个字段保持 `None`。成员原生来源中已有的图片所属文档、媒体版本等信息仍由相应适配器完整保留，不用容器身份覆盖。

## 容器与成员关联

`HandoffReport.status` 原样保留原生 ZIP 的整包状态，包括 `partial_success`。报告通过以下 metadata 字段保存资料集合边界：

| 字段 | 含义 |
| --- | --- |
| `metadata.container.source` | 原生 ZIP 来源。 |
| `metadata.container.business_id`、`version` | 调用方明确给出的容器业务身份；未知为 `None`。 |
| `metadata.container.counts` | 原生的 total、success、failed、ignored、unprocessed 计数。 |
| `metadata.container.error`、`stop_reason`、`total_bytes_read` | 原生容器错误、停止原因与读取量；不重新计算处理结果。 |
| `metadata.container.requires_review` | 原生 ZIP 的待核验汇总；技术成功不表示质量已核验。 |
| `metadata.members` | 按原 ZIP 条目顺序保存的完整成员清单，包括目录、失败、忽略和未处理成员。 |
| `metadata.members[*].source` | 完整的 container、member_path、entry_index；entry_index 为包含目录的一基原条目序号。 |
| `metadata.members[*].format`、`status`、`result_kind` | 原成员格式、处理状态与原生结果类别。 |
| `metadata.members[*].error`、`reason`、`bytes_read` | 原成员错误、原因与读取量。 |
| `metadata.members[*].document_ids` | 指向本报告 `documents` 的 ID 列表；没有原生解析结果时为空。 |

同名路径的两个条目保留两条成员记录和不同的文档 ID，不按文件名合并。通过成员记录的 `document_ids` 查询独立文档，再通过文档内单元的 `source_ids` 查询页、节点、表格行、图片或媒体片段来源；不把成员序号当作业务版本。

## 状态与正文边界

成功成员各自保留完整正文，互不拼接。节点、行列、服务块等沿用相应适配器的实际定位粒度，不推测 Markdown 字符映射。服务页序与原生 PDF 页序继续分别表示，HTML 主部分、服务结构与产物、图片原图映射、媒体片段时间均随成员文档保留。

有失败原生解析结果的成员仍关联一份失败诊断文档：正文为 `None`、内容单元为空，来源和原解析错误仍可查看。没有原生结果的失败、忽略或未处理成员只保留成员记录及原错误/原因，不制造正文或文档。容器级错误另外写入报告的 `zip_error` 诊断，不关联虚构文档。

ZIP 成员的技术 `success` 不覆盖子结果的 `no_text`、`uncertain` 或待核验标记。空文字保持原状态；整包部分成功、空包、损坏包和全失败包均可导出 JSON。

验证使用既有 ZIP 和媒体样本、本地 HTTP 服务，边界为真实上游 ZIP 结果 → 公开 `adapt_result` → UTF-8 JSON 导出回读。测试在适配前关闭服务，检查输入未被修改、成员关联、整份报告内 ID 唯一性和真实来源。

```powershell
python -m unittest tests.test_handoff_zip -v
python -m unittest discover -s tests -p 'test_handoff_*.py' -v
```
