# 数字 PDF 固定样本与核验记录

日期：2026-10-27。解析环境：共享项目虚拟环境，pypdf 6.21.2。只使用文本层提取，扫描样本本次仅核验“需要 OCR”的诊断，不运行识字。

## 原始教学样本

以下文件从仓库外的教学记录复制，字节未修改；SHA-256 同历史解析原始记录一致。

| 仓库样本 | 原始来源 | SHA-256 | 已知原文及用途 |
| --- | --- | --- | --- |
| `pdf_digital_teaching.pdf` | [数字PDF.pdf](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/数字PDF.pdf) | `6567b43bf59c2ee4794ca32df98eebb6b2edab5311018ebc607a23da01350b03` | 第 1 页依次为 Equipment Maintenance、Disconnect power before maintenance.、Inspect every month.；核验完整正文、标题文字、断电规则和检查周期 |
| `pdf_scanned_teaching.pdf` | [扫描PDF.pdf](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/扫描PDF.pdf) | `caf14142d35a2399b6cb2a4115b3ae9774ada2b8605109acc0f8409ec1899c2b` | 第 1 页是图像，无可用文本层；公开入口应报告第 1 页需要 OCR，不以图片引用、换行或占位返回成功正文 |

原始生成方法可回查[快速验证.py](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/快速验证.py:36)，历史提取事实见[解析原始结果.json](/E:/projectOfLearning/Agent学习/MeLearn/学习记录/parse-03-PDF与Word/P1-20261009/解析原始结果.json:20)。验收只读取本仓库副本，不依赖仓库外路径。

## 本地构造样本

通过[生成脚本](/C:/Users/29157/.codex/worktrees/pdf-word-digital/rag-me/tests/testFile/build_digital_pdf_samples.py)生成固定 PDF。使用 PDF 标准字体 Helvetica 和明确的文本绘制指令，预期正文来自下面列出的输入文字；不从转换结果自动生成测试预期，也不在测试运行时重新生成文件。

| 样本 | SHA-256 | 构造与预期事实 |
| --- | --- | --- |
| `pdf_digital_page_order.pdf` | `c1f39ad1d73f3f3b750cc848572caecd09cbb30438c800dcf51fed0e6ba6c132` | 两页。第 1 页依次为 Maintenance Start、Disconnect power before maintenance.、Printed page 41；第 2 页依次为 Maintenance Finish、Inspect every month.、Printed page 7。必须按物理顺序输出，来源页序为 1、2，各字符区间只能指向对应页文字 |
| `pdf_digital_corrupt.pdf` | `dfadfd2f2a3d1153683b06f981808789c44ae67be08e4f93d22ff78cb19980fb` | 只有 PDF 文件头和损坏说明，缺少 xref/trailer；两个公开入口均返回明确解析失败，正文为 None |
| `pdf_digital_damaged_page.pdf` | `59af769d439eea650c4c12b9a9abb561d0d326d87f71ba142bc2a5c7beb6b31e` | 从两页样本生成，第 2 页内容流替换为未闭合字符串；返回第 2 页提取失败，不把第 1 页冒充整篇 |
| `pdf_digital_blank.pdf` | `a8b2418093183bedab01ffcbf32923a5abc2ba4eb4962ba4580cfc6c4f7479c2` | 一页空正文、无图像；两个入口均报告无可用正文，并保留第 1 页的警告，不生成虚假正文来源 |

重新生成构造样本：在仓库根目录执行 `python tests/testFile/build_digital_pdf_samples.py`；随后核对摘要并运行测试。教学副本不由此脚本重新生成。

## 实际 red → green 证据

所有轮次均先修改公开行为测试、运行得到失败，再补实际实现并运行通过：

1. 原始教学 PDF：red 为缺少 `convert_file`；green 为完整三行正文及第 1 页来源通过。
2. 字节入口与文件入口等价：red 为缺少 `convert_bytes`；green 为相同来源、格式、正文和来源区间通过。
3. 多页正文与来源：red 为页面边界缺少空行的正文断言失败；green 为两页全文、顺序及对应区间通过。
4. 外部字节参数：red 为非法格式/来源仍成功、非法类型抛异常；green 为失败诊断与正文隔离通过。
5. 文件读取和参数失败：red 为缺失文件、目录及非法参数直接抛异常；green 为明确失败结果通过。
6. 损坏 PDF：red 为未处理的 PdfStreamError；green 为文件和字节入口的解析失败诊断通过。
7. 扫描 PDF：red 为换行字符串误报成功；green 为正文 None、来源为空、第 1 页需要 OCR 的诊断通过。
8. 文本层局限：red 为没有标题、双栏、表格恢复局限警告；green 为独立警告存在且不混入正文。
9. 页面损坏：red 为第 2 页抛出未处理的 PdfStreamError；green 为第 2 页的失败诊断、无部分成功正文通过。

扫描样本的无正文修复完成后，再用无图像空白页核验同一失败约定，未增加业务分支。最终共 10 个公开行为测试。

不据此宣称标题层级、复杂双栏、表格关系或扫描识字质量通过。当前未测量性能，不报告准确率或速度提升。
