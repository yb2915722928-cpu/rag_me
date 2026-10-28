# 文档来源与原图映射

公开入口 `convert_file` / `convert_bytes` 的 `document`、`crop` 和 `is_cropped` 参数共用同一来源契约。来源独立放在结果的 `source` 中，正常正文、空 OCR 和失败都能保留已确定的事实；所有模型文字仍需核验。

## 文档来源

```python
from importlib import import_module

images = import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
document = images.DocumentSource(
    document_id="payment-policy",
    business_version="approved-2026-10",
    position=images.DocumentPosition(kind="pdf_page", index=3),
)
result = images.convert_file("page-image.png", task="ocr", document=document)
```

`DocumentPosition.kind` 仅接受 `pdf_page`（实际 PDF 页序）或 `slide`（实际幻灯片序号），`index` 是从 1 开始的整数，不是印刷页码或正文块序号。二者即便序号相同也保持不同类型。已知标识和业务版本必须是非空字符串，原值不被规范化或改写。

独立图片无需提供 `document`。文档标识、业务版本、位置各自可为 `None`，例如只知道文档标识时用 `DocumentSource(document_id="payment-policy")`。核心不会从文件名、图片文字或模型输出推断未知字段。

## 已经裁剪的图片

```python
from pathlib import Path

crop = images.CropMapping(
    original_image_id="archive/payment-rules/source-image-01",
    original_width=1200,
    original_height=600,
    bbox=(120, 180, 1120, 440),
)
result = images.convert_bytes(
    Path("cropped.png").read_bytes(),
    format="png", source="upload/cropped.png", task="ocr",
    document=document, is_cropped=True, crop=crop,
)
```

调用方已知输入是裁剪图时应传 `is_cropped=True`；此时缺少整组 `crop` 也会在公开入口失败。单独提供 `crop` 同样表示原图映射，无需重复声明。模块无法从像素判断一张图片过去是否被裁剪，调用方必须如实声明。

`CropMapping` 的原图标识、原图宽高和矩形必须完整提供。宽高为正整数，`bbox` 是四个整数的元组 `(left, top, right, bottom)`，约定为原图左上原点、0 基像素坐标、右下边界不含：

```text
0 <= left < right <= original_width
0 <= top < bottom <= original_height
```

不完整、错误类型、空矩形或越界返回 `invalid_options`，不会静默按整图处理。校验只发生在公开入口；后续任务不重复解释调用方来源。模型请求仅携带图片与任务指令，文档和裁剪元数据不交给模型生成或修改。

## 回查结果

| 结果字段 | 含义 |
| --- | --- |
| `source.location` | 本次实际输入文件路径或调用方的输入标识 |
| `source.sha256` | 本次实际输入字节的 SHA-256；裁剪输入的摘要仍属于裁剪图片 |
| `source.width` / `source.height` | 本次输入成功解码后的像素尺寸 |
| `source.document` | 调用方的原文档标识、业务版本及有类型位置 |
| `source.crop.original_image_id` | 调用方原图标识，与输入摘要及业务版本相互独立 |
| `source.crop.original_width` / `original_height` | 调用方给出的原图像素尺寸 |
| `source.crop.bbox` | 本次整张裁剪图片在原图中对应的已知矩形 |

示例中输入尺寸为 1000×260，原图尺寸为 1200×600；文字回查到原图的 `(120,180,1120,440)`。未提供裁剪映射的整图结果仅关联 `location` / `sha256` 标识的输入整图，`crop=None`，不生成细分区域、逐字框或正文字符区间。

同字节在不同文档出现时保留不同文档来源；同名不同字节保留不同摘要。来源数据类不可变，模型输出与来源结果分离。正常空 OCR 的正文是空字符串，失败正文是 `None`，二者都能保留有效来源。未解码时输入宽高保持 `None`，即使已知原图宽高也不会拿来填充输入尺寸；未读到字节时摘要保持 `None`。元数据校验失败仍保留已确定的输入标识，以及此前通过校验的文档来源。

模块验证元数据完整性和范围，不验证调用方原图身份或像素是否真的匹配；本期不执行裁剪，不推算旋转／透视，不负责原图存储及访问方式。SHA-256 和原图标识都不被当作可打开的图片地址。来源可回查不等于 OCR 内容正确。

## 固定样本与验收

样本、构造脚本、来源清单和真实证据均在 [tests/testFile](/E:/aaa-project/rag-me/tests/testFile/)，名称以 `image_provenance_` 开头；构造图无网络下载，运行测试不重建。详细记录见 [image_provenance_acceptance.md](/E:/aaa-project/rag-me/tests/testFile/image_provenance_acceptance.md)。

```powershell
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_provenance tests.test_image_ocr -v
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest discover -s tests -q

# 只有显式启用才消耗真实 API；核心入口仍不隐式加载环境文件。
$env:STEP_PROVENANCE_LIVE_TEST = '1'
$env:STEP_ENV_FILE = 'E:\aaa-project\rag-me\.env'
$env:STEP_PROVENANCE_LIVE_EVIDENCE = 'tests/testFile/image_provenance_live_evidence.json'
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_provenance_live -v
```
