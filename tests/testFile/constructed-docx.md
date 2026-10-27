# DOCX 固定样本与实验记录

对应 GitHub [Issue #10](https://github.com/yb2915722928-cpu/rag_me/issues/10) 与父规格 [#8](https://github.com/yb2915722928-cpu/rag_me/issues/8)。测试固定读取本仓库副本，不依赖历史路径、不在测试运行中重新生成样本，不从转换结果生成预期。

## 来源、构造与摘要

教学副本原始字节来自[历史表格 DOCX](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/表格DOCX.docx)。原始生成步骤见[快速验证.py](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/快速验证.py:49)，其身份与正文顺序可对照[历史解析记录](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/P1-20261009/解析原始结果.json)。副本 SHA-256 与历史记录相同。

其余样本由 [build_docx_samples.py](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/build_docx_samples.py) 使用 python-docx 1.2.0 构造；损坏包通过固定字节、替换正文 XML 或移除正文部件生成。重新生成可在仓库根目录执行 `python tests/testFile/build_docx_samples.py`；教学副本不会被改写。DOCX ZIP 时间戳可能随重建改变，重建后需重新核对摘要；下表对应本次提交的固定字节。

| 固定输入 | SHA-256 | 预期事实 |
| --- | --- | --- |
| [docx_teaching.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_teaching.docx) | `f2d5801529016b10e0c8fbd6558a0e5e9b88f2b892a3ba4b5a3f6ebb62030ec3` | 一级标题 Equipment Maintenance → Disconnect power before maintenance. → Equipment/Interval 表，Pump/Monthly → Restart after inspection.；共 4 块 |
| [docx_sections.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_sections.docx) | `4ea46f33f99dfe92854c0cc0597699aa0270199d987ef69fdb288103888069e8` | 前言、三级标题、同级切换、同名一级标题；泵—每月、阀门—每季度；表在断电与重启说明之间；共 14 块，其中第 7 块为空段落，只输出 13 个区间 |
| [docx_table_cells.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_table_cells.docx) | `201cb6867d12ef7dd3b8113ac057efcb4993565f75513bdfda591c3dbf6bc455` | 首单元格包含竖线、泵名包含反斜杠；周期内换行与追加段落仍在原单元格；标题和表格各一块 |
| [docx_outline_headings.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_outline_headings.docx) | `563de105f79dbda8a26c448e440210f7a31cab3e9f3c3273d1b553b690904eb2` | 改名一级标题、继承二级标题、段落直接指定三级大纲；名称为 Heading Notes 的普通样式仍为段落 |
| [docx_deep_headings.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_deep_headings.docx) | `67e6b4a2db8fb4fbd93547dd542e0589db669c1c13041fe950428053aff2c177` | 原生 6/7/9 级；Markdown 限于 6 级，来源保留 6/7/9，第 2、3 块独立提示降级 |
| [docx_empty.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_empty.docx) | `300b3c1716bbe8be8aa68182987919584661738de07beb6bc907f33113a17bb0` | 空白段落、空白标题、空表格；无可用正文，失败且不生成虚构来源 |
| [docx_corrupt.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_corrupt.docx) | `6f8b8ea9595c6ad2246733b7eb73a974b231c50837dea4fea0d302a9b8ea2c9a` | 固定字节 not a DOCX package；损坏 ZIP 失败 |
| [docx_invalid_xml.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_invalid_xml.docx) | `129376621383412af11578761b28a4058be18a5ac1662bb5b9d633a0b055ae01` | 教学副本的正文替换为不完整 XML，失败 |
| [docx_missing_part.docx](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/tests/testFile/docx_missing_part.docx) | `7957bc089e3f4e2a66872b421ec286eb8d376eea2c1da12506f8475c80cd07df` | 教学副本移除正文部件，失败 |

## red→green 观察

2026-10-27 使用共享项目 venv 的 Python 3.12.8、python-docx 1.2.0、lxml 6.1.3，工作目录为独立 DOCX worktree。以下每项先新增一个公开入口测试并运行失败，再添加对应实现并运行通过；所有期望正文和来源元组为已知输入事实的字面量。

| 行为切片 | Red 的实际观察 | Green |
| --- | --- | --- |
| 历史正文顺序与标题/表格 | Unsupported format: docx | 原生顺序输出完整 Markdown |
| file/bytes 来源关联 | 来源数量为 0，预期 4 | 来源切片、章节及 1–4 计数正确，两个入口一致 |
| 两设备、多级章节与空块 | 空段落在 Markdown 中额外生成空行 | 第 7 块占位、不输出；第 8 块保持章节第 3 块；两组对应关系不变 |
| 损坏文件诊断 | BadZipFile、XMLSyntaxError、KeyError 直接抛出 | 两入口返回失败结果，正文与来源为空 |
| 全空文档 | 空表分隔符被当成成功正文 | No usable text body in DOCX |
| 单元格边界 | 竖线拆列、单元格换行拆行 | 转义及 `<br>` 保留单元格归属 |
| 原生标题 | Heading Notes 导致 ValueError；改名/继承标题未恢复 | 根据直接/继承大纲级别保留 1–3 级和章节 |
| 支持边界与诊断隔离 | 警告为空 | 警告独立于已验证正文 |
| 超过 Markdown 的标题深度 | 7/9 个井号不能表示有效 Markdown 标题 | Markdown 限于 6 级，来源保留原生深度，警告定位正文块 |

公开入口复现及精确计数规则见 [DOCX 说明](/C:/Users/29157/.codex/worktrees/pdf-word-docx/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/DOCX.md)。本切片不执行 OCR、API 调用、文档导出或切块；不把普通表格样本通过推广为合并/嵌套表格无损支持。
