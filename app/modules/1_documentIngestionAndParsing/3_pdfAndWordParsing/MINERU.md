# 纯扫描 PDF：MinerU 官方精准解析 API

Issue #11 使用[现行官方云 API](https://mineru.net/apiManage/docs)。数字 PDF 继续本地文本层；DOCX 使用原生结构。本切片只处理纯扫描 PDF，数字/扫描混合文档的逐页派发和合并由 #12 完成。

## 公开调用

```python
import importlib

parsing = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
api = parsing.MinerUConfig(language="en")
result = parsing.convert_file("scan.pdf", mineru=api)
same = parsing.convert_bytes(pdf_bytes, format="pdf", source="scan.pdf", mineru=api)
```

`mineru` 是两个公开入口的可选关键字参数。省略时使用默认 `MinerUConfig()`，Token 从进程环境变量 `MINERU_API_TOKEN` 读取；也可显式设置 `MinerUConfig(token=...)`，Token 不进入配置对象的 repr。模块不加载任何环境文件。调用者只在需要扫描识字时配置凭据，数字 PDF 不因此依赖网络。

配置字段：`token=None`、`api_base="https://mineru.net/api/v4"`、`language="ch"`、`poll_interval=3`、`request_timeout=30`、`max_wait=300`，时间单位为秒。`max_wait` 限定上传完成后的轮询等待；每个网络操作另受 `request_timeout` 约束。测试通过 `api_base` 接入本地 HTTP 服务，运行同一上传、轮询和 ZIP 解析实现。

成功仍返回 `ConversionResult`。每个有正文的实际 PDF 页占一个 `ContentSource`，`extraction_method="mineru_api"`，页序从 1 开始，字符区间左闭右开。页间生成的空行不属于原页正文。不使用印刷页码或处理进度总页数定位。失败时正文为 `None`、来源列表为空；错误和警告独立返回。

## 实际协议

1. POST `/api/v4/file-urls/batch`：一个 `document.pdf` 文件，`is_ocr=true`；顶层固定 `model_version="vlm"`、`enable_table=true` 和所选语言。
2. 按返回地址 PUT PDF 原始字节。签名上传不附带管理 API 凭据或 Content-Type；标准库 urllib 自动添加的表单类型在本次真实服务上触发过 403，因此此处使用标准库 http.client 明确发送原始 PUT。
3. 上传后自动创建任务，不再二次提交。按 batch_id GET `/api/v4/extract-results/batch/{batch_id}`，识别 waiting-file/pending/running/converting/done/failed。
4. done 后下载 ZIP，在内存读取真实 `*_content_list.json` 或 `content_list.json`。不按上传文件名构造云端随机前缀，不误读 `*_content_list_v2.json`，不依赖最新开源 4.0 自托管产物格式。

管理 API 仅使用 Authorization Bearer 认证，不使用旧 pro 文档的额外 token 用户头。当前官方单文件限制为 200 MB、200 页；本地上传接口章节写每批 50 个文件，页面总览仍写 200，本切片只上传一个文件。超额及格式错误通过业务状态码返回独立诊断，不增加自动分片或后台服务。

HTTP 失败、业务 code 非零、远端 failed、未知状态、等待超时、非法响应、损坏 ZIP、缺少旧版内容列表、非法 page_idx、缺失正文页均返回明确诊断。返回错误会去除当前凭据及 URL；不记录请求头或签名地址。没有自动重提任务或本地 OCR 回退。

## 正文、表格与来源

按旧版内容列表实际 `page_idx` 分页，保持页内块顺序。text 保留正文，text_level 转换为 Markdown 标题，table_body 保留 HTML 表格以保留行列关系。full.md 是云端整篇输出，不能靠其换行可靠还原页序，因此应用正文与来源均从结构化列表建立。

只含图片、空文字或缺少应识字页面时不能报告整篇成功。表格仅返回截图或平铺词语时独立警告“table relationships were not recovered”，不把它记为结构恢复。本实现没有导出 bbox：旧版 content_list 的 bbox 为 0–1000 归一化位置，不是图片像素或原 PDF 点坐标。

识字输出仍需对照原文核验否定词、数字、单位、标题与关系。代表样本通过不承诺任意复杂表格、跨页表格或版面无损；本切片不增加其他格式转换或多 provider 框架。依赖只有标准库和项目已声明的 pypdf，无本机 OCR/模型/渲染运行时依赖。

## 默认测试与显式真实验收

```powershell
python -m unittest tests.test_pdf_word_mineru -v
python -m unittest discover -s tests -v
```

默认测试启动真实本地 HTTP 服务，在公开 file/bytes 入口验证协议、正文、来源和失败；不替换内部协作者，也不据此声称云端 OCR 质量通过。凭据环境读取测试只控制环境变量这一系统边界。默认不会读取环境文件或调用云 API，真实验收类默认跳过。

调用者已在本机设置 `MINERU_API_TOKEN` 后，显式启用真实教学样本验收：

```powershell
$env:MINERU_LIVE_TEST='1'
python -m unittest tests.test_pdf_word_mineru_live -v
```

不要在聊天、命令输出或提交中展示 Token。`MINERU_LIVE_EVIDENCE` 可指定脱敏结果 JSON 的输出位置；不设置时不写文件。实时运行会提交实际解析任务，仅在明确需要复测时启用。

## 2026-10-27 已完成的真实验收

通过公开 convert_file 运行两页扫描表格教学 PDF：约 25.847 秒，完整保留断电说明、Do not service while power is on、30 days、60 C、Pump—Monthly、Valve—Quarterly，表格仍在说明与 Restart 段落之间。来源为实际第 1、2 页，没有使用印刷页码 41、7。首个标题返回二级 Markdown 标题，第二页标题未返回层级；不将标题文字存在等同于任意标题层级恢复。

输入摘要、生成方法、red→green 记录和脱敏真实结果见[扫描样本说明](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/tests/testFile/constructed-scanned-pdf.md)。原历史扫描教学样本曾在本地 OCR 漏字；真实 MinerU 研究探针完整恢复两条规则，该记录保留为历史对照，不改写旧失败观察。探针成功与本次公开入口成功分别记录。
