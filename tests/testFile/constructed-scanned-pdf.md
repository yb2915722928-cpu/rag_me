# 扫描 PDF 固定样本及 Issue #11 核验

日期：2026-10-27。默认协议测试通过公开入口运行真实本地 HTTP 服务；下述质量证据来自显式真实 MinerU 调用，二者不混记。

## 固定输入

- [原扫描教学副本](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/tests/testFile/pdf_scanned_teaching.pdf)：4931 字节，SHA-256 `caf14142d35a2399b6cb2a4115b3ae9774ada2b8605109acc0f8409ec1899c2b`。与[原教学资料](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/扫描PDF.pdf)字节相同；第 1 页只有图像，预期 Disconnect power before maintenance. / Inspect every month.。
- [扫描表格样本](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/tests/testFile/pdf_scanned_maintenance_table.pdf)：SHA-256 `3c4bdd3465f6450a26be3b6074ada31f3c82f2b56ce6506cf03db998d383c0c0`。两页纯图像，无可提取文本层；第 1 页为标题、断电说明、不得带电维护、30 天检查、Equipment/Interval 表格（Pump/Monthly、Valve/Quarterly）、重新启动说明和印刷页码 41；第 2 页为 Inspection Limits、Temperature must not exceed 60 C. 及印刷页码 7。

生成源头是[build_scanned_pdf_samples.py](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/tests/testFile/build_scanned_pdf_samples.py)。使用 Pillow 12.3.0 内置字体（不依赖系统字体），在 1800×2400 白底上绘制文字和表格线；pypdf 6.10.0 将 RGB 图像作为每页唯一主体写入 600×800 点的 PDF，不写文本指令。Pillow 仅用于一次性样本生成，不加入业务运行时依赖，测试只读取固定产物。

```powershell
& 'C:\Users\29157\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B tests/testFile/build_scanned_pdf_samples.py
```

使用上述现有捆绑环境重建；更换生成依赖版本后应重新核对摘要，不能手改生成 PDF。

## 真实结果

[mineru_live_maintenance_table.json](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/tests/testFile/mineru_live_maintenance_table.json)来自公开 convert_file，使用共享项目 Python、pypdf 6.21.2、标准库 HTTP；实际模型配置 vlm、language=en。耗时 25.847 秒。正文、否定词、30 days、60 C 均通过原文定向核验，三行 HTML 表格分别为 Equipment/Interval、Pump/Monthly、Valve/Quarterly；来源区间指向 PDF 实际页序 1、2。未对正文进行业务纠错或填回预期文字。

[mineru_live_historical_probe.json](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/tests/testFile/mineru_live_historical_probe.json)是先前直接 API 研究探针，原扫描教学 PDF 两条规则完整恢复，总耗时 14.616 秒，旧版内容列表两个 text 块、page_idx=0。它不是本模块公开入口运行，和新的公开入口证据分别标识。

原 Windows OCR 1×、2× 均漏字的[历史观察](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/P1-20261009/实验观察.md)未修改。不能从倍率试验单独归因，也不把历史错漏当成本次云 API 结果。新结果只证明声明样本，不承诺任意复杂扫描表格或完整 RAG 链路通过。

两份真实证据不包含 Token、请求头或签名 URL。原环境文件没有复制到仓库。真实表格证据已验收，不为写报告重复调用 API。

## 实际 red → green

1. file/bytes 上传—轮询—ZIP 成功：red 为没有 MinerUConfig；green 为完整两句正文、第 1 页来源及两入口等价。
2. 无凭据：red 为 HTTP 异常外泄；green 为正文 None、来源为空、页序与 MINERU_API_TOKEN 配置诊断。
3. 表格和两页来源：red 为 table 块按 text 读取而 KeyError；green 为标题、表格原位、两组对应关系和两个页区间。
4. 远端 failed：red 为失败状态继续轮询后误报成功；green 为页级失败诊断。
5. 等待期限：red 为超过期限仍继续并成功；green 为明确 polling timed out。
6. 错误脱敏：red 为错误消息含测试凭据与模拟签名 URL；green 为移除相关信息。
7. 真实 PUT：首次 live 返回 403，未进入识字；本地 HTTP 服务拒绝 urllib 自动添加的 Content-Type 重现 red，改用标准库原始 PUT 后 green，后续真实两页扫描表格通过。
8. HTTP 各阶段失败：red 为 apply/poll/download 抛出未处理的 HTTPError；green 为业务失败结果。
9. 漏页：red 为缺少第 2 页仍报告成功；green 为指出第 2 页且不返回部分正文。
10. 表格截图/平铺词语：red 为缺字段异常或没有损失警告；green 为保留可用正文并明确表格关系未恢复。
11. API 业务失败：red 为 HTTP 200 中非零 code 被当成成功数据；green 为业务码与原因。
12. 非法 JSON、ZIP、缺少旧版列表：red 为 JSONDecodeError、BadZipFile、StopIteration；green 为独立诊断。
13. 内容列表结构与页索引：red 为越界/缺字段导致错误来源或异常；green 为在外部结果边界一次校验。
14. 上传/轮询协议缺失及未知状态：red 为 KeyError 或继续等待后误成功；green 为协议诊断。
15. 非法可选配置：red 为 AttributeError；green 为 file/bytes 入口配置错误结果。

额外回归确认环境变量凭据读取、图片/空文字不得作为正文。没有 mock 内部解析器或 client；本地 HTTP 服务只替代外部 MinerU 系统边界。真实验收通过测试类显式 opt-in，默认 unittest 跳过。
