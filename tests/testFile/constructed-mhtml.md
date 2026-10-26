# MHTML 构造样本（Issue #6）

2026-10-26 本地构造，共 28 个固定输入，均在本目录以 `mhtml_` 开头。测试只读取已保存文件，不联网、不在测试中生成输入。六份公开下载样本及来源摘要记录均未修改；两个 Chromium 原始 MHTML 仍按下载字节验收。

公共构造方式：ASCII MIME 头、CRLF 头部/边界换行、固定 boundary `mhtml-fixture` 的 `multipart/related; type="text/html"`；每部分默认 `text/html; charset=utf-8`、`8bit` 传输编码。下表列出例外及可独立核对的事实。无 `start` 时，逐部分完成严格解包和解码，比较原始 HTML 的 Unicode 字符数，包含标记、注释及 CRLF；不比较字节数、清理后文本数或 Markdown 长度。并列保留 MIME 顺序。单一候选仍需启发式警告。

| 样本 | 构造方式与核对事实 |
| --- | --- |
| [mhtml_start_shorter.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_start_shorter.mhtml) | 第一部分是重复 80 次的长框架正文；`start="<main-page>"` 指向第二部分，正文含标题 Main page 和 Start chooses this shorter page.。其 nav 在正文提取模式删除，在整页模式保留；不产生最大字符数警告。 |
| [mhtml_character_count.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_character_count.mhtml) | 两部分都用 `<html><body><p>…</p></body></html>` 包裹：第一部分 30 个“中”，63 字符/123 UTF-8 字节；第二部分 50 个 A，83 字符/83 字节。应选第二部分 `<characters-winner>`。两个候选都有 ID，ID 单独存在不代表主标识。 |
| [mhtml_raw_html_count.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_raw_html_count.mhtml) | 第一部分正文为重复 20 次的 Visible text；第二部分注释中含 500 个 x，正文只有 Raw markup winner。应选原始 HTML 更长的第二部分 `<raw-winner>`，不按 Markdown 长度选择。 |
| [mhtml_character_tie.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_character_tie.mhtml) | 相同包裹中分别是 First tied page 和 Other tied page，均 48 字符；选 MIME 顺序靠前的 `<first>`。 |
| [mhtml_original_crlf_count.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_original_crlf_count.mhtml) | 第一部分 50 个 A，共 83 字符；第二部分注释中含 20 个 CRLF，正文 CRLF winner，共 91 原始字符。若先转 LF 则只有 71 字符，会选错；应选第二部分 `<original-winner>`。 |
| [mhtml_declared_gb18030.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_declared_gb18030.mhtml) | 中文 HTML 编成 GB18030 后以 `quopri.encodestring` 编码；MIME 声明 GB18030、HTML meta 故意声明 UTF-8。MIME 优先；严格解码得到“长江流经武汉，黄河流经兰州。”。显式错误 UTF-8 不回退。 |
| [mhtml_meta_gb18030.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_meta_gb18030.mhtml) | 同一中文正文和 QP 编码，MIME 无 charset，HTML meta 声明 GB18030；使用 HTML 声明。 |
| [mhtml_invalid_declaration.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_invalid_declaration.mhtml) | 同一中文正文，MIME 编码名 no-such-text-codec 不存在，HTML meta 声明 GB18030；独立警告后按 HTML 声明成功。 |
| [mhtml_utf8_bom_conflict.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_utf8_bom_conflict.mhtml) | 中文 HTML 用 UTF-8-SIG 编码并 base64 折行；MIME 和 meta 都错误声明 ASCII。BOM 优先；显式 UTF-8 优先时实际编码记录为 utf-8。 |
| [mhtml_utf16_bom_conflict.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_utf16_bom_conflict.mhtml) | 同一中文 HTML 用 UTF-16 LE BOM 编码并 base64 折行，MIME/meta 错误声明 ASCII；按 BOM 解码。指定 UTF-8 必须失败。 |
| [mhtml_declaration_before_utf8.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_declaration_before_utf8.mhtml) | café 实际编码 UTF-8；MIME 声明 ISO-8859-1，HTML meta 声明 UTF-8。按 MIME 声明得到 cafÃ©，显式 UTF-8 得到 café；证明 MIME 声明在 HTML 声明及有效 UTF-8 尝试之前，不声称修复错误声明。 |
| [mhtml_utf8_no_declaration.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_utf8_no_declaration.mhtml) | 同一中文正文，载荷 UTF-8，无 MIME/meta 编码声明；使用 UTF-8。 |
| [mhtml_detected_gb18030.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_detected_gb18030.mhtml) | 将既有 [html_detected_gb18030.html](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/html_detected_gb18030.html) 的原始载荷嵌入归档，不声明编码；探测后核对武汉、兰州、北京、故宫等事实，记录实际编码及独立探测警告。 |
| [mhtml_undecodable.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_undecodable.mhtml) | HTML 部分的原始载荷为 `bytes(range(256))`，base64 封装，无 charset；严格 UTF-8 和探测均不能完成，失败。 |
| [mhtml_truncated_utf16.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_truncated_utf16.mhtml) | HTML 载荷为 FF FE 17（UTF-16 LE BOM 加截断码元），base64 封装；不得忽略字节或回退。 |
| [mhtml_start_ignores_unselected_decode_error.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_start_ignores_unselected_decode_error.mhtml) | 第一部分为上述截断 UTF-16；`start="<valid>"` 指向第二部分 Only the selected HTML needs decoding.。不需要解码未选框架，转换成功。 |
| [mhtml_fallback_decode_error.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_fallback_decode_error.mhtml) | 与上一样本载荷相同但没有 start，无法取得全部严格字符数，应失败，不能静默跳过坏部分后声称选出最大者。 |
| [mhtml_unmatched_start.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_unmatched_start.mhtml) | start 指向不存在的 `<missing>`，即使另有可读 HTML 仍明确失败。实现只匹配当前外层 related 的直接 HTML 子部分，不跨层匹配其他框架；不实现通用 MIME 引用图。 |
| [mhtml_no_html.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_no_html.mhtml) | 只有纯文本和 image/png 部分，不能变成 HTML 正文；无需解码图片或导出附件。 |
| [mhtml_html_attachment.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_html_attachment.mhtml) | 唯一 HTML 声明 `Content-Disposition: attachment`；附件不进入主 HTML 候选。 |
| [mhtml_empty_root.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_empty_root.mhtml) | start 指向只有 title/style/script 的第二部分，第一部分为长可读正文；选中根无正文应失败，不换页。仍保留选中 ID、MIME 序号和实际编码。 |
| [mhtml_empty_largest.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_empty_largest.mhtml) | 无 start，第二部分 script 中有 300 个 x，原始字符最多但无正文；失败并保留选中来源和启发式警告，不换成较短可读部分。 |
| [mhtml_qp_truncated.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_qp_truncated.mhtml) | QP 载荷末尾孤立等号；stdlib email 会静默丢弃，局部 escape 检查应明确失败。 |
| [mhtml_qp_bad_escape.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_qp_bad_escape.mhtml) | QP 载荷包含非法 `=QZ`，不能冒充已成功解包的正文。 |
| [mhtml_base64_truncated.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_base64_truncated.mhtml) | 将 `<p>Broken transfer!</p>` base64 编码后删除末尾 `==`；严格解包必须失败，不能自动补齐。 |
| [mhtml_base64_invalid.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_base64_invalid.mhtml) | 上述有效 base64 末尾追加 `!!`；不能忽略杂字符后当作成功。 |
| [mhtml_unknown_transfer.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_unknown_transfer.mhtml) | 声明 x-unknown 传输编码，载荷虽看似 HTML 也不能当成已解包的正文。 |
| [mhtml_truncated_mime.mhtml](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/testFile/mhtml_truncated_mime.mhtml) | 删除末尾 MIME 关闭 boundary；严格解析失败并提供非空结构原因。 |

[公开转换与导出测试](/C:/Users/29157/.codex/worktrees/rag-me-issue-6/tests/test_text_web_mhtml.py:13)只检查返回结果和实际导出文件，不访问内部解析函数、不 mock 解析器。失败结果既不能创建文件，也不能覆盖已有文件。来源与警告不拼入 Markdown。

来源字段沿用输入 location/format；新增 encoding、content_id、content_location、mime_index（根为 0 的 MIME walk 原始序号）。缺失 ID/Location 为 None；编码与既有结果顶层 encoding 相同。Chromium 单页原始 HTML 为 249 字符；多框架为 500/173/174/281/212 字符，均无 start，选中第一部分并产生启发式警告，不合并框架。图片仍沿用 HTML 空扩展点。
