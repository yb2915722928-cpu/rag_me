# 演示文稿：本地构造样本

这些文件由 [构造脚本](/E:/aaa-project/rag-me/tests/testFile/build_pptx_samples.py) 使用 python-pptx 1.0.2 与 Pillow 创建，无外部下载。所有业务内容均为教学假设；默认测试读取保存后的固定字节，不在运行期间造输入。

| 样本 | 构造与验收目的 |
| --- | --- |
| [退款审批](/E:/aaa-project/rag-me/tests/testFile/pptx_refund.pptx) | 共 8 页。原第 8 页有标题、先创建的右栏企业订单、后创建的左栏普通订单、企业专属金额条件、带箭头端点的连接线和备注。核验页归属、对象分离、层级、图层顺序及待核验诊断。 |
| [视觉与表格](/E:/aaa-project/rag-me/tests/testFile/pptx_visual.pptx) | 无标题页，包含经过平移和缩放的组合、两层文本、Markdown/HTML 符号、带文本的箭头形状、横向合并单元格、图表、图片及嵌入工作簿。核验 ID 路径、父容器内原始坐标与诊断，嵌入文件不展开。 |
| [普通与纵向合并表格](/E:/aaa-project/rag-me/tests/testFile/pptx_tables.pptx) | 第一张为普通 2×2 表格，含 HTML 字符和换行；第二张为纵向合并表格。核验普通行列、转义、rowspan 与原始单元格来源，不把第一行认作表头。 |
| [纯图片页](/E:/aaa-project/rag-me/tests/testFile/pptx_image_only.pptx) | 只有脚本生成的纯色图片，正文只有原页标识并要求核验，不宣称有 OCR 正文。 |
| [无幻灯片](/E:/aaa-project/rag-me/tests/testFile/pptx_empty.pptx) | 合法的空演示包，明确失败。 |
| [损坏包](/E:/aaa-project/rag-me/tests/testFile/pptx_corrupt.pptx) | 固定非 ZIP 字节，验证格式失败。 |
| [末页损坏](/E:/aaa-project/rag-me/tests/testFile/pptx_atomic_failure.pptx) | 从退款样本复制包，将第 8 页 XML 替换为不完整标记；前 7 页有效，仍不得返回部分正文。 |
| [末页对象损坏](/E:/aaa-project/rag-me/tests/testFile/pptx_atomic_shape_failure.pptx) | 第 8 页 XML 语法有效，但首个正文对象 ID 非整数。包可打开，提取有效前 7 页后处理末页失败，整篇正文、来源及待核验诊断必须清空。 |
| [成员压缩损坏](/E:/aaa-project/rag-me/tests/testFile/pptx_corrupt_compression.pptx) | 保留 ZIP 目录与成员头，仅把末页压缩流改为无效 DEFLATE 块类型。复现 zlib 解压异常，两个公开入口均须返回失败结果。 |
| [非标准后缀](/E:/aaa-project/rag-me/tests/testFile/pptx_override.bin) | 与退款包字节相同，使用显式格式覆盖后缀，来源仍为实际输入路径。 |

重建：`python tests/testFile/build_pptx_samples.py`。生成文件不要手改；修改脚本后重新生成。PPTX 包时间戳可能随重建改变，不依赖整包摘要判断业务等价性。
