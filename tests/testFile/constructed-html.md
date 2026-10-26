# HTML 构造样本（Issue #5）

这些输入于 2026-10-26 在本地构造，无下载、JavaScript 执行或图片访问。所有新增输入均以 `html_` 开头，存放在本目录；沿用目录 Git 属性保留原始字节。公开教程样本及六份下载材料的来源摘要记录保持不变。

除下表明确标注的编码或损坏字节外，文件均为 UTF-8、无 BOM、LF 换行。通过[公开转换与导出测试](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/test_text_web_html.py:14)读取真实文件，不在测试中重新生成输入。

| 样本 | 构造方式与核对事实 |
| --- | --- |
| [html_structure.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_structure.html) | 手写三层标题、嵌套列表、两列两行表格、带查询参数的文字链接；正文内外放置语义导航/侧栏/页脚及 class/id 广告标记。正文模式去噪，整页模式保留这些附属文字；两模式均排除标题元信息、脚本、样式、noscript、template。 |
| [html_code_whitespace.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_code_whitespace.html) | 手写 pre/code，含两端空行、制表符、行尾空格、连续空行、三反引号及 span 包裹的代码。纯空格行用三个 `&#32;` 表示，解析后仍为三个空格。断言整个代码文本。 |
| [html_candidate_main.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_candidate_main.html) | main 前后均有普通段落，正文只取候选，整页包含候选外段落。 |
| [html_candidate_article.htm](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_candidate_article.htm) | article 候选，同时验证 htm 后缀路由。 |
| [html_candidate_role.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_candidate_role.html) | role=main 候选，周围段落不属于正文。 |
| [html_fallback_fragment.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_fallback_fragment.html) | 不含 body 的片段，main 为空；清理导航和页脚后回退到剩余内容。download 类名不能因包含字母 ad 而被删。无编码声明时使用 UTF-8。 |
| [html_images.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_images.html) | 不存在的图片地址夹在两段文字之间；只核对文字及无图片警告，不要求图片处理效果。 |
| [html_script_only.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_script_only.html) | 标题、脚本、样式、空挂载点和非正文占位，不含静态正文；两模式失败。 |
| [html_title_only.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_title_only.html) | 省略 head/body 的 title 与脚本；标题元信息不能成为成功正文。 |
| [html_noise_only.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_noise_only.html) | 只有导航、侧栏、广告和页脚；正文模式失败。 |
| [html_declared_gb18030.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_declared_gb18030.html) | 将带 meta charset=GB18030 的中文页面严格编码为 GB18030；已知事实为“长江流经武汉，黄河流经兰州。”。 |
| [html_http_equiv_gb18030.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_http_equiv_gb18030.html) | 同上，改用大写 META、http-equiv=Content-Type、content 中带单引号的 charset，且属性顺序颠倒。 |
| [html_explicit_override.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_explicit_override.html) | 实际 GB18030、错误声明 UTF-8；调用方指定 GB18030 应优先成功。 |
| [html_utf8_bom_conflict.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_utf8_bom_conflict.html) | 中文页面通过 Python 的 utf-8-sig 编码，故意声明 ISO-8859-1；BOM 优先。显式 UTF-8 又优先于 BOM，并记录 utf-8 而非 utf-8-sig。 |
| [html_utf16_bom_conflict.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_utf16_bom_conflict.html) | 中文页面通过当前 Windows/Python 的 utf-16 编码，含 LE BOM、错误声明 ISO-8859-1；自动按 BOM 解码，显式错误 UTF-8 则失败。 |
| [html_declaration_before_utf8.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_declaration_before_utf8.html) | 故意将 UTF-8 的 café 声明为 ISO-8859-1：按声明得到 cafÃ©，证明声明先于有效 UTF-8；显式 UTF-8 可得到 café。不宣称自动修复错误声明。 |
| [html_invalid_declaration.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_invalid_declaration.html) | UTF-8 中文正文，依次声明不存在的编码及无法解码中文的 ASCII；独立记录两条警告，然后采用 UTF-8。用于验证诊断不进入实际导出文件。 |
| [html_detected_gb18030.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_detected_gb18030.html) | 将既有 TXT 构造样本的 GB18030 正文放入无编码声明的 HTML；探测后核对武汉、兰州、北京等事实及独立警告。 |
| [html_undecodable.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_undecodable.html) | 逐字节复制既有不可解码 TXT 构造样本，不提供可用编码；失败且正文为 None。 |
| [html_truncated_utf16.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-5/tests/testFile/html_truncated_utf16.html) | 中文 HTML 编为含 BOM 的 UTF-16 后删除最后一个字节，制造截断；严格解码失败，不回退猜测。 |

原始 Python 教程通过公开文件入口核对 Data Structures、More on Lists、Using Lists as Stacks、已知段落及 fruits 的代码。新增测试还通过公开字节入口验证格式大小写与来源，通过导出入口读取 UTF-8 实际文件，失败结果不得创建正文文件。

正文提取只使用明确的 main/article/role=main 与常见内容容器候选；同类多个候选取清理后文本最长的一个，无可用候选时回退到清理后的 body 或片段。此规则不保证任意网页都可完美提取，调用方可选整页模式。
