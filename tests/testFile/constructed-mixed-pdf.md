# 混合 PDF 固定样本及 Issue #12 核验

日期：2026-10-27。默认行为测试使用真实本地 HTTP 系统边界；真实识字证据来自公开文件入口的一次 MinerU 云 API 调用。

## 输入、来源及重建

[四页混合样本](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/pdf_mixed_maintenance.pdf)：109198 字节，SHA-256 `4d87b329c3d618ba54a6a8bacd870e595186104e26eb56ea6f46224b701e1c71`。

| 原 PDF 页序 | 路径与独立事实 | 印刷页码 | 上传后的 API 索引 |
| --- | --- | --- | --- |
| 1 | 数字文本：Digital Intake、Asset code: PUMP-A17. | 90 | 不上传 |
| 2 | 扫描图：Equipment Maintenance、断电、不得带电维护、每 30 天检查、设备周期表、Restart | 41 | 0 |
| 3 | 数字文本：Digital Release、Torque setting: 12 Nm. | 12 | 不上传 |
| 4 | 扫描图：Inspection Limits、Temperature must not exceed 60 C. | 7 | 1 |

[生成源头](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/build_mixed_pdf_samples.py)以 pypdf 6.21.2 为数字页写入 Helvetica 文本指令，交错复制 #11 的[两页扫描表格样本](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/pdf_scanned_maintenance_table.pdf)，没有重新绘制或修改扫描内容。扫描输入 SHA-256 为 `3c4bdd3465f6450a26be3b6074ada31f3c82f2b56ce6506cf03db998d383c0c0`，其图像生成和历史质量观察沿用[原说明](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/constructed-scanned-pdf.md)。

仓库根目录使用共享项目 Python 3.12.8 重建：

```powershell
& 'C:\Users\29157\.codex\worktrees\pdf-word-integration\rag-me\.venv\Scripts\python.exe' -B tests/testFile/build_mixed_pdf_samples.py
```

固定输入由源头生成；测试只读取固定产物。没有手工改写 PDF 或真实输出 JSON。

## 离线行为与实际 red → green

已确认 seam 为公开文件和字节转换入口；沿用 unittest。使用 #11 的真实本地 HTTP 服务，运行真实 pypdf、选页复制、客户端上传/轮询/ZIP 读取及合并，不 mock 内部函数或 MinerUClient。离线返回的内容列表只用于协议和映射验证，不算 OCR 质量证据。

1. file/bytes 混合成功：red 为 `OCR required for PDF pages: 2, 4`；green 为两入口返回相同完整正文，来源页序 1、2、3、4，路径交替为 text_layer/mineru_api。HTTP 接收端检查每次只有一份上传、仅两页、无文本层；内容流、图像字节和尺寸分别对应原第 2、4 页。数字第 1、3 页的两个独立事实及逐页正文区间按已知字面值核验，没有串页或重复拼接。
2. 漏掉任一扫描页：red 为原第 4 页缺失却报告第 2 页，或原第 2 页缺失却报告第 1 页；green 为分别指出原第 4、2 页。两入口均不返回部分成功正文，markdown 为 None、sources 为空。
3. 无凭据：red 为错误与警告使用选页 PDF 的 1–2 页；green 为仅指向原第 2、4 页，并提供 MINERU_API_TOKEN 配置诊断。
4. 远端 failed：red 为报选页 PDF 的 1–2 页；green 为报告此次待识字的原第 2、4 页和实际原因，不把数字页正文当作整篇成功。
5. 表格损失：red 为 API 第 1 索引的表格损失被报告为第 2 页；green 为指明原第 4 页，平铺词语可保留但独立警告关系未恢复，不把警告写入正文。

```powershell
python -m unittest tests.test_pdf_word_mixed -v
python -m unittest discover -s tests -v
```

合并集成分支最新 tip `50129d3` 后，完整回归共 108 项，106 项通过、2 项真实云 API 测试按默认设置跳过，耗时 4.601 秒；覆盖数字 PDF、纯扫描协议、DOCX 与文本网页。混合真实验收另行显式运行，1 项通过，默认跳过不替代下述真实证据。

## 真实 API 运行与结果

[自动保存的真实证据](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/mineru_live_mixed.json)来自[公开入口验收测试](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/test_pdf_word_mixed_live.py)。环境为 Windows、Python 3.12.8、pypdf 6.21.2；复用 #11 客户端和标准库 HTTP，model_version=vlm、language=en、enable_table=true，默认 3 秒轮询、30 秒请求超时、300 秒轮询期限。2026-10-27 02:08:52 UTC 保存结果，公开转换本身实测 **9.570 秒**。

此次只从原环境文件读取 MINERU_API_TOKEN 到测试子进程，没有加载其他配置、复制环境文件或保存请求头/Token/签名 URL。调用一次公开文件入口；字节入口等价性与上传原页内容由离线行为测试验证，不为验收重复运行所有 #11 质量样本。

调用方已在测试进程设置 Token 后，仓库根目录复现：

```powershell
$env:MINERU_MIXED_LIVE_TEST='1'
$env:MINERU_MIXED_LIVE_EVIDENCE='tests/testFile/mineru_live_mixed.json'
python -m unittest tests.test_pdf_word_mixed_live -v
```

真实结果的来源区间为原页 1 `[0,53)`、原页 2 `[54,360)`、原页 3 `[361,416)`、原页 4 `[417,486)`，均为 Python 字符串索引；页间空行不属于原页正文。前述两项数字事实逐字保留，五项维护规则和温度上限在各自扫描页通过定向核验，其他页没有重复出现这些事实。全部正文按来源区间和页间分隔符可还原，来源路径按原页交替排列。API 0、1 返回的扫描内容映射至原页 2、4，没有使用印刷页码定位。

实际扫描第 2 原页返回 HTML 表格，行内容为 Equipment/Interval、Pump/Monthly、Valve/Quarterly；表格位于断电说明与 Restart 之间。复用相同扫描输入使此次也可核验两组关系；#11 的其他真实质量记录保持原样，没有为写报告重复 API 调用。

## 局限

- 文本层非空不足以证明文字正确或结构完整。沿用现有非空文本层优先规则，不自动发现所有错误隐藏文字，也不声称能理解或纠正任意业务事实。
- 数字页保留标题文字，不自动生成标题层级；扫描首页返回二级标题，另一扫描页只有标题文字。复杂双栏、跨页表格、合并单元格仍需人工对照。
- 混合合并只负责选页、原页映射和顺序，不修补上游 OCR 漏字或表格关系损失。服务失败只定位本批待识字原页；没有依据时不猜具体单页。
- 来源是实际 PDF 页序，不是印刷页码。本模块没有导出 OCR bbox，也不生成图片像素与原 PDF 坐标的虚假映射。
- 依赖 MinerU 网络、凭据和配额，无多 provider 或本机 OCR 回退。默认测试不会访问云 API；代表样本通过不等于完整 RAG 上传、检索、问答或引用链路通过。

## 最终 review 修复回归（2026-10-27）

新增固定输入 `pdf_mixed_numbered_scan.pdf`，109451 字节，SHA-256 `e7a9ef051bd8bbeb772e155f70100528e94b08c5baef21ea3fc16baf96b9557a`。它复制上述四页混合样本，仅在第 2 页叠加可提取的 `Printed page 41` 隐藏文本，保留原扫描图、页面尺寸和其他三页；不生成新 OCR 文字或改写历史真实结果。只需项目声明的 pypdf 即可重建该变体：

```powershell
python -B tests/testFile/build_numbered_scan_pdf_sample.py
```

[公开入口行为测试](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/test_pdf_word_mixed.py)验证两种调用：默认路径第 2 页只有页码、没有维护规则，并明确警告非空文字不能证明文本层质量；传入 `ocr_pages=(2,)` 后，第 2 页与自动发现的第 4 页一起复制上传，API 0、1 映射回原页 2、4。返回正文完整包含断电、不得带电维护、30 days、设备周期表和重启说明；原第 1、3 数字页保持原文，每页只有一个来源区间，`Printed page 41` 仅出现一次。若第 2 页没有返回 OCR 正文，整篇明确失败，不退回页码文本。

本轮逐项 red → green 的实际观察：

- 列表正文：纯 list 页原先返回 `No usable OCR body for PDF page 1`；修复后 file/bytes 均完整保留三条规则及第 1 页来源。
- 表格附属文字：整篇 Markdown 对比先显示表题、附属说明与禁令脚注缺失；修复后按表题 → HTML 表格 → 脚注顺序保留，设备周期关系及两页来源区间通过。[MinerU 行为测试](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/test_pdf_word_mineru.py)还复现了错误字段类型导致成功或未捕获异常；修复后 list_items、table_caption、table_footnote 只在 JSON 入口检查为字符串数组，错误作为独立诊断返回。
- 显式选页：默认路径已实际复现只有页码而遗漏扫描规则；首次传入参数报 `unexpected keyword argument 'ocr_pages'`。修复后两个公开入口均按上述原页序替换正文，并保留其他数字页。
- 参数诊断：错误类型原先异常或被忽略，越界页序原先仍返回成功；修复后明确拒绝非整数元组、布尔值、零/负数和超出实际页数的页序。DOCX 非空选择原先被忽略，现明确拒绝。错误结果均无成功正文或来源列表。
- 声明依赖：干净 Python 3.11 原测试取 image.data 时抛出 `ImportError: pillow is required to do image extraction`；改为读取 PDF XObject 图像内容流，仍核对上传页与原扫描页内容、图像及尺寸，随后通过，无需 Pillow 或 pypdfium2。
- 文档链接：8 份新增文档的 36 处 worker 链接改为保留的集成工作树。包含本节新增引用的 49 个本地链接目标全部存在；历史 E 盘来源和真实 JSON 未改写。

本轮验证均为本地真实 HTTP 协议与公开 file/bytes 行为，不重复收费 API；新增协议测试不宣称新增云端识字质量证据，上述历史 live 记录仍保持原样。完成前已合并集成最新 tip `63bdec1`（Already up to date）。

最终完整回归命令为 `python -m unittest discover -s tests -v`，显式关闭两个 live 开关。共享 Python 3.12.8：117 项，115 通过、2 live 跳过，8.327 秒；仅安装 requirements 的干净 Python 3.11.16：117 项，115 通过、2 live 跳过，8.680 秒。后者确认没有 Pillow、pypdfium2；本轮没有增改依赖或重跑收费 API。
