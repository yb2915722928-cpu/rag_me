# ZIP 容器

逐成员受限读取 ZIP，返回整包摘要和逐成员原生结果，不拼接全包正文。TXT/Markdown、JSON/XML、CSV 复用轻量本地解析；PDF（含数字 PDF）、DOCX、PPTX、XLSX、HTML/MHTML 默认使用 MinerU，图片和音视频默认使用阶跃 API。没有云端启用开关，API 缺配置或失败不自动回退本地重解析。

各类参数、来源语义及真实验收入口分别见[文档 API](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/DOCUMENTS.md)、[图片 API](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/IMAGES.md)和[音视频 API](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/MEDIA.md)。使用运行时 MINERU_API_TOKEN、STEP_API_KEY、STEP_BASE_URL、STEP_MODEL；可选 STEP_ASR_MODEL 沿用既有默认值。核心和 CLI 不自动载入环境文件。

公开入口见 [convert_file / convert_bytes](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__init__.py)，预算和结果见 [models.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/models.py)。Python 需要 3.11 或以上，依赖沿用仓库现有安装流程。

```python
from importlib import import_module
from pathlib import Path

zip_containers = import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
report = zip_containers.convert_file(
    "documents.zip",
    source="upload-42.zip",
    limits=zip_containers.ZipLimits(max_total_bytes=32 * 1024**2),
    parser_options={"csv": {"delimiter": ";", "encoding": "gb18030", "mode": "rows"}},
)
same_boundary = zip_containers.convert_bytes(
    Path("documents.zip").read_bytes(), source="upload-42.zip",
)
payload = report.to_dict()
```

文件入口从文件句柄读取，不先把整个归档载入内存；字节入口由调用方提供 `bytes`。`source` 在字节入口必填，在文件入口默认输入路径。无格式覆盖参数，成员按自己的后缀分派，解析器验证真实内容。结构化 JSON 采用保留节点路径的入口；CSV 保留原值、列名与原始记录位置。

`parser_options` 按 `text`、`structured`、`csv`、`document`、`image`、`media` 分类传入。容器只检查外层类别和映射形状，子解析器负责自己的选项；不得覆盖 `source`、`format` 或 `limits`。正文编码属于相应类别；`metadata_encoding` 仅控制归档名称编码，不猜测修复中文文件名，ZIP 自带 UTF-8 标志优先。

## 状态与来源

`members` 按中央目录顺序排列，每项保存 `source.container`、原始 `source.member_path` 和从 1 开始（包含目录）的 `source.entry_index`。不同目录同名和同路径重复条目都独立处理；下游来源为 `容器!/成员#序号`，其页、节点、单元格或媒体位置仍保留原义。

| 字段 | 含义 |
| --- | --- |
| 成员 status | `success` / `failed` / `ignored` / `unprocessed`。 |
| result_kind / result | 处理器类别及原生结果；不把原生错误、警告塞入正文。 |
| reason / error | 容器拒绝、读取或解析失败与停止原因；无失败时为 None。原生结构化诊断仍完整保存在 result。 |
| bytes_read | 此成员占用的展开读取预算，失败不退还。 |
| 整包 status | 有成功且无失败/未处理为 `success`；两类并存为 `partial_success`；无成功为 `failed`。 |
| counts | `total`、`success`、`failed`、`ignored`、`unprocessed`。 |
| success | 仅整包完整成功为真；空包、仅元数据、全失败不成功。 |
| requires_review | 汇总原生结果，和提取是否成功独立，不代表质量已经核验。 |
| error / stop_reason | 容器级诊断与全局停止原因；成员错误仍在各自条目。 |
| total_bytes_read | 所有成员已占用的展开预算。 |

仅目录、独立路径段 `__MACOSX`、`.DS_Store` 和 AppleDouble（文件名以 `._` 开头）忽略；其他隐藏文档仍处理。内嵌 ZIP、加密标志、未知格式、绝对/盘符/UNC/父目录跳转路径、CRC/读取错误、解析错误都有成员诊断。危险路径不会自动改名，容器从不解压或按成员名称写盘。DOCX/XLSX/PPTX 的 ZIP 封装不视为递归归档。

## 预算与截止

| ZipLimits 字段 | 默认值 |
| --- | --- |
| max_archive_bytes | 100 MiB 压缩输入 |
| max_members | 1000 条中央目录条目（含目录/忽略项） |
| max_member_bytes | 64 MiB 单成员展开量 |
| max_total_bytes | 256 MiB 累计展开量 |
| timeout_seconds | 300 秒协作式截止 |

默认值是初始策略，不是实测服务器容量。正整数预算及有限正数截止在公开入口校验一次。压缩大小和条目数失败时不解析任何成员；成员声明大小先预检，再以最多 64 KiB 的读取块实际计量。单成员超限仅失败该成员；累计预算不足或截止到达时，当前未完成和后续文档为未处理，已知元数据仍忽略，完成项保留。

CRC 失败的读取调用不会返回当前块，预算按本次请求与剩余声明范围保守计费。预算限制容器持有的展开输入，不能声称限制标准库解压器、子格式解码或媒体准备的所有内存。截止在成员与读取块间检查，不能强制打断运行中的解析器/API；外部请求仍采用自己的超时。

远端结果 ZIP 同样受调用方 `ZipLimits` 约束，分派独立传递该对象。每个结果包分别执行下载、成员数、单成员与累计展开量限制，不混入输入容器的 total_bytes_read。这里不引入批处理、自动重试、任务队列或沙箱。

## CLI

入口见 [__main__.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__main__.py)。在仓库根目录运行：

```powershell
python -m app.modules.1_documentIngestionAndParsing.8_zipContainers tests/testFile/zip_text.zip
python -m app.modules.1_documentIngestionAndParsing.8_zipContainers tests/testFile/zip_budgets.zip --max-total-bytes 8
python -m app.modules.1_documentIngestionAndParsing.8_zipContainers tests/testFile/zip_legacy_names.zip --metadata-encoding gb18030 --parser-options '{"text":{"encoding":"utf-16"}}'
```

stdout 是 UTF-8 JSON，包含计算得到的整包/原生成功与待核验属性；不序列化调用方配置。退出码：完整成功 `0`、部分成功 `2`、业务失败 `1`。argparse 用法错误仍为 `2`，其输出写到 stderr 且不产生业务 JSON；集成脚本应同时检查 JSON 是否产生。

可以指定 `--source`、`--max-archive-bytes`、`--max-members`、`--max-member-bytes`、`--max-total-bytes`、`--timeout-seconds`；`--parser-options` 只接收按类别组织的 JSON。CLI 不自动加载环境文件，也不把配置写进报告。

## 格式分派

[dispatch.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/dispatch.py) 的 `convert_member(data, *, format, source, parser_options, limits)` 通过明确分支返回 `(result_kind, 原生结果)`。各独立适配文件接收本类别选项，文档适配器额外接收同一个 `limits`。不使用注册系统、通用插件接口或跨业务模块重构。

原生结果以自己的 `success` 判断，包括正常空文字；待核验不会改成失败，异常只隔离到对应成员。API 缺配置或调用失败必须明确失败，不能回退到本地重解析。

## 验证

基础固定样本与构造方法见 [zip_samples.md](/E:/aaa-project/rag-me/tests/testFile/zip_samples.md)，基础 red → green 和命令见 [IMPLEMENTATION.md](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/IMPLEMENTATION.md)。默认测试通过公开文件/字节入口运行真实本地解析或本地 HTTP 协议服务，CLI 使用真实子进程；显式真实 API 验收与默认协议回归分别记录，不把可控响应当作识别质量证据。
