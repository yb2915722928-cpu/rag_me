# 扫描与混合 PDF：MinerU 官方精准解析 API

Issue #11 使用[官方云 API](https://mineru.net/apiManage/docs)，Issue #12 复用同一客户端处理混合 PDF。数字页继续本地文本层，扫描页复制为一份选页 PDF 上传；DOCX 使用原生结构。没有新增 provider、本机 OCR 或其他上传服务。

独立 PDF 的选页与页序逻辑位于本包的 [MinerU 包装器](mineru.py)，通用上传、轮询和下载复用 [共享客户端](../mineru_client.py)。旧路径 `3_pdfAndWordParsing.mineru` 与本包 `mineru` 引用相同的客户端、`MinerUConfig` 和 `MinerUError`。ZIP 内文档继续按托管文档策略上传完整原文件；本包的选页策略只用于独立 PDF。

## 公开调用

```python
import importlib

parsing = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction"
)
api = parsing.MinerUConfig(language="en")
result = parsing.convert_file("scan.pdf", mineru=api)
same = parsing.convert_bytes(pdf_bytes, format="pdf", source="scan.pdf", mineru=api)
```

`mineru` 是两个公开入口的可选关键字参数。省略时使用默认 `MinerUConfig()`，Token 从进程环境变量 `MINERU_API_TOKEN` 读取；也可显式设置 `MinerUConfig(token=...)`，Token 不进入配置对象的 repr。模块不加载任何环境文件。调用者只在需要扫描识字时配置凭据，数字 PDF 不因此依赖网络。

两个入口还接受 `ocr_pages=()`。默认只自动识字无文字且含图像的页面，文字非空不能证明文本层质量：扫描正文可能仅有页码或页眉可提取。调用方核验后可用 `convert_file("mixed.pdf", mineru=api, ocr_pages=(2,))`，或 `convert_bytes(pdf_bytes, format="pdf", source="mixed.pdf", mineru=api, ocr_pages=(2,))`，要求识字原 PDF 实际第 2 页并替换该页文本层结果。参数只接受整数元组（不接受布尔值），页序从 1 开始，必须在实际 PDF 页数范围内，不能使用印刷页码；类型、范围错误或对 DOCX 使用非空选择均返回明确诊断。它不自动判断文本层质量，也不引入本机 OCR。

配置字段：`token=None`、`api_base="https://mineru.net/api/v4"`、`language="ch"`、`poll_interval=3`、`request_timeout=30`、`max_wait=300`，时间单位为秒。`max_wait` 限定上传完成后的轮询等待；每个网络操作另受 `request_timeout` 约束。测试通过 `api_base` 接入本地 HTTP 服务，运行同一上传、轮询和 ZIP 解析实现。

成功仍返回 `ConversionResult`。每个有正文的实际 PDF 页占一个 `ContentSource`，`extraction_method="mineru_api"`，页序从 1 开始，字符区间左闭右开。页间生成的空行不属于原页正文。不使用印刷页码或处理进度总页数定位。失败时正文为 `None`、来源列表为空；错误和警告独立返回。

## 实际协议

1. POST `/api/v4/file-urls/batch`：一个 `document.pdf` 文件，`is_ocr=true`；顶层固定 `model_version="vlm"`、`enable_table=true` 和所选语言。
2. 按返回地址 PUT PDF 原始字节。签名上传不附带管理 API 凭据或 Content-Type；标准库 urllib 自动添加的表单类型在本次真实服务上触发过 403，因此此处使用标准库 http.client 明确发送原始 PUT。
3. 上传后自动创建任务，不再二次提交。按 batch_id GET `/api/v4/extract-results/batch/{batch_id}`，识别 waiting-file/pending/running/converting/done/failed。
4. done 后下载 ZIP，在内存读取真实 `*_content_list.json` 或 `content_list.json`。不按上传文件名构造云端随机前缀，不误读 `*_content_list_v2.json`，不依赖最新开源 4.0 自托管产物格式。

混合 PDF 在上述流程前只复制需要识字的原页，包括显式选择的非空文本页与自动选中的扫描页，保持页面内容流、图像及页面尺寸；全页均需识字时仍上传原始字节。上传文件的 API `page_idx` 按选页后的零基顺序解释，例如原第 2、4 页对应 API 0、1。正文来源、漏页、无凭据、服务失败及表格损失诊断均使用原 PDF 页序；批次失败无法进一步定位单页时列出本批原页，不猜测失败页。两条路径的正文按原 PDF 页序合并，每页仅有一个来源区间；所选页使用 OCR 正文替换文本层，未选数字页仍使用本地结果，不重复追加页码。待识字页失败时整篇失败，不回退为只有页码的成功正文。

管理 API 仅使用 Authorization Bearer 认证，不使用旧 pro 文档的额外 token 用户头。当前官方单文件限制为 200 MB、200 页；本地上传接口章节写每批 50 个文件，页面总览仍写 200，本切片只上传一个文件。超额及格式错误通过业务状态码返回独立诊断，不增加自动分片或后台服务。

HTTP 失败、业务 code 非零、远端 failed、未知状态、等待超时、非法响应、损坏 ZIP、缺少旧版内容列表、非法 page_idx、缺失正文页均返回明确诊断。返回错误会去除当前凭据及 URL；不记录请求头或签名地址。没有自动重提任务或本地 OCR 回退。

## 正文、表格与来源

按旧版内容列表实际 `page_idx` 分页，保持页内块顺序。text 保留正文，text_level 转换为 Markdown 标题；list_items 按返回顺序保留各项和已有编号，纯列表页也属于可用正文。表格按 table_caption → table_body → table_footnote 顺序保留，HTML 表格保持行列对应，题注和脚注与表格同属原页来源区间。三个附属字段遵循[官方旧版契约](https://github.com/opendatalab/MinerU/blob/mineru-2.5.4-released/docs/en/reference/output_files.md)，均为字符串数组，只在外部 JSON 入口校验一次，不做多版本兼容框架。full.md 是云端整篇输出，不能靠其换行可靠还原页序，因此应用正文与来源均从结构化列表建立。

只含图片、空文字或缺少应识字页面时不能报告整篇成功。表格仅返回截图或平铺词语时独立警告“table relationships were not recovered”，不把它记为结构恢复。本实现没有导出 bbox：旧版 content_list 的 bbox 为 0–1000 归一化位置，不是图片像素或原 PDF 点坐标。

识字输出仍需对照原文核验否定词、数字、单位、标题与关系。代表样本通过不承诺任意复杂表格、跨页表格或版面无损；本切片不增加其他格式转换或多 provider 框架。依赖只有标准库和项目已声明的 pypdf，无本机 OCR/模型/渲染运行时依赖。

## 默认测试与显式真实验收

```powershell
python -m unittest tests.test_pdf_word_mineru -v
python -m unittest tests.test_pdf_word_mixed -v
python -m unittest discover -s tests -v
```

默认测试启动真实本地 HTTP 服务，在公开 file/bytes 入口验证协议、正文、来源和失败；不替换内部协作者，也不据此声称云端 OCR 质量通过。凭据环境读取测试只控制环境变量这一系统边界。默认不会读取环境文件或调用云 API，真实验收类默认跳过。

调用者已在本机设置 `MINERU_API_TOKEN` 后，显式启用真实教学样本验收：

```powershell
$env:MINERU_LIVE_TEST='1'
python -m unittest tests.test_pdf_word_mineru_live -v
```

单独复测混合 PDF（不重复 #11 的独立扫描验收）：

```powershell
$env:MINERU_MIXED_LIVE_TEST='1'
$env:MINERU_MIXED_LIVE_EVIDENCE='tests/testFile/mineru_live_mixed.json'
python -m unittest tests.test_pdf_word_mixed_live -v
```

该测试只通过公开文件入口执行一次真实任务，记录原始结果与输入摘要，检查四页的独立事实、顺序、来源区间及 API 0、1 → 原页 2、4 的映射。两个公开入口的等价性及实际上传内容由默认本地 HTTP 测试共同验证。

不要在聊天、命令输出或提交中展示 Token。`MINERU_LIVE_EVIDENCE` 可指定脱敏结果 JSON 的输出位置；不设置时不写文件。实时运行会提交实际解析任务，仅在明确需要复测时启用。

## 2026-10-27 已完成的真实验收

通过公开 convert_file 运行两页扫描表格教学 PDF：约 25.847 秒，完整保留断电说明、Do not service while power is on、30 days、60 C、Pump—Monthly、Valve—Quarterly，表格仍在说明与 Restart 段落之间。来源为实际第 1、2 页，没有使用印刷页码 41、7。首个标题返回二级 Markdown 标题，第二页标题未返回层级；不将标题文字存在等同于任意标题层级恢复。

输入摘要、生成方法、red→green 记录和脱敏真实结果见[扫描样本说明](../../../../tests/testFile/constructed-scanned-pdf.md)。原历史扫描教学样本曾在本地 OCR 漏字；真实 MinerU 研究探针完整恢复两条规则，该记录保留为历史对照，不改写旧失败观察。探针成功与本次公开入口成功分别记录。

混合样本经公开文件入口处理耗时 9.570 秒：数字原第 1 页资产编号 PUMP-A17、第 3 页扭矩 12 Nm 逐字保留；两页扫描正文落在原第 2、4 页，断电、不得带电维护、30 days、60 C 和两组表格对应关系通过。正文中印刷页码 90、41、12、7 没有被当成来源页序。扫描首页标题实际为二级标题，另一扫描页只返回标题文字，仍不承诺统一标题层级。详见[混合固定样本与真实记录](../../../../tests/testFile/constructed-mixed-pdf.md)。文本非空不足以证明文字正确或结构完整，混合合并也不会修补上游 OCR 或版面损失；不代表完整 RAG 链路通过。
