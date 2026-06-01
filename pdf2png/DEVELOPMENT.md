# pdf2png 开发总结

| 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 语言 | Python 3.13 | 核心逻辑 |
| PDF 渲染 | PyMuPDF (pymupdf) 1.26.7 | 页面→像素数据 |
| 图片处理 | Pillow 11.3.0 | 像素数据→PNG、长图拼接 |
| 进度条 | tqdm 4.67.1 | 渲染进度显示 |
| ZIP 打包 | stdlib zipfile | PNG→ZIP 压缩 |
| 通配符展开 | stdlib glob | `*.pdf` 模式匹配 |
| 命令行入口 | .cmd 批处理 | cmd/PowerShell 通用调用 |
| 包管理 | pip | 依赖安装 |

## 架构设计

```
pdf2png.cmd          →  包装器，定位并调用 pdf2png.py
pdf2png/
  pdf2png.py         →  核心：解析参数 → 验证 → 渲染 → 输出
  README.md          →  使用文档
  DEVELOPMENT.md     →  开发总结（本文档）
```

### 命令行参数

```
pdf2png [-z] [-l [N]] <pdf_file> [pdf_file2 ...] [save_path]

  -z       将 PNG 打包为 ZIP
  -l [N]   每 N 页纵向合并为一张长图（N: 1-4，默认 4）
```

`-z` 和 `-l` 可任意组合。参数解析顺序：先提取所有标志 → 识别 `save_dir` → 展开通配符 → 剩余为 PDF 文件列表。

### 渲染管线

```
PDF 页面
  ↓  fitz.get_pixmap(dpi=200)
fitz.Pixmap (RGB / RGBA / CMYK / 灰度)
  ↓  pixmap_to_pil(): 色彩空间归一化 + Image.frombytes
PIL Image
  ↓
  ├─ 逐页模式: 直接 save("PNG")
  └─ 合并模式: 分组 → merge_images_vertical() → save("PNG")
  ↓
  ├─ 默认: 输出到 <basename>/ 文件夹
  └─ -z: 输出到临时目录 → zipfile → 清理临时文件
```

**关键设计决策：**

- **.cmd 而非 .ps1 作为入口**：.ps1 受 PowerShell 执行策略限制（Restricted/RemoteSigned），.cmd 在 cmd 和 PowerShell 下均可直接运行，零配置。
- **不打包时创建同名文件夹**：`pdf2png mydoc.pdf` → `mydoc/mydoc_1.png, mydoc_2.png`，避免 PNG 散落在当前目录。
- **打包时使用临时目录**：`tempfile.mkdtemp()` 存放中间 PNG，ZIP 创建后自动 `shutil.rmtree()` 清理。
- **批量错误不中断**：`validate_pdf()` 返回 `None` 而非 `sys.exit()`，单文件失败后继续处理下一个，最后输出成功/失败汇总。
- **长图合并以最大宽度为画布**：各页宽度可能不同（横排/竖排混用），以组内最宽页为准，其余页水平居中，白色背景。
- **合并文件命名区分单页与多页**：多页组用 `_1-4.png`，尾部单页用 `_7.png` 而非 `_7-7.png`，更简洁。

## 遇到的问题与解决

### 1. fitz 模块命名冲突

**现象**：`import fitz` 报错 `RuntimeError: Directory 'static/' does not exist`，但 PyMuPDF 已安装。

**原因**：site-packages 中存在另一个包 `frontend`，它在 site-packages 下安装了 `fitz/` 目录，覆盖了 PyMuPDF 的 fitz 模块路径。

**解决**：PyMuPDF 同时支持 `import fitz` 和 `import pymupdf` 两种导入方式。改用 `import pymupdf as fitz`，绕过命名冲突，其余代码无需修改。

### 2. Windows GBK 终端 Unicode 编码报错

**现象**：`print("✓ 转换完成")` 抛出 `UnicodeEncodeError: 'gbk' codec can't encode character '✓'`。

**原因**：Windows 中文版终端默认使用 GBK 编码，`✓`（U+2713）不在 GBK 字符集内。

**解决**：在脚本开头强制重配置 stdout/stderr 为 UTF-8：
```python
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
```
`errors="replace"` 确保万一有不支持的字符也不会崩溃，会用 `?` 替代。

### 3. PowerShell 下 tqdm 导致 NativeCommandError

**现象**：PowerShell 中运行后显示 `NativeCommandError`，退出码为 1，但实际转换成功。

**原因**：tqdm 默认输出到 `sys.stderr`。PowerShell 将任何来自原生命令的 stderr 输出视为错误，自动包装为 `NativeCommandError`。

**解决**：tqdm 初始化时显式指定 `file=sys.stdout`：
```python
with tqdm(..., file=sys.stdout) as pbar:
```

### 4. 通配符展开与 save_dir 识别顺序错误

**现象**：`pdf2png ./*.pdf /output_dir` 将 `/output_dir` 当作待转换的 PDF 文件报错。

**原因**：`expand_globs()` 在 `save_dir` 识别之前执行。`./*.pdf` 展开后参数变为 `['a.pdf', 'b.pdf', 'c.pdf', '/output_dir']`，此时 `/output_dir` 排在末尾，但 `os.path.isdir()` 对其返回 False（目录不存在时），于是被当作 PDF 文件。

**解决**：调换执行顺序 — 先在原始参数上识别 `save_dir`（通配符展开前），再做 glob 展开。判断一个参数是否为目录的依据：
1. `os.path.isdir()` 返回 True（已存在的目录）
2. 以 `/` 或 `\` 结尾（明确指定为目录）
3. basename 中不含 `.` 且含路径分隔符（推断为目录路径）

带有 `.pdf` 扩展名的文件名不会被误判（basename 含 `.`）。

### 5. 长图合并时的色彩模式与宽度差异

**现象**：纵向拼接时不同页面的色彩模式不同（RGB/RGBA/灰度），直接 `paste()` 报错或颜色异常。

**原因**：Pillow 的 `paste()` 要求被粘贴图像与画布色彩模式兼容。RGBA 图直接贴到 RGB 画布上会报 `ValueError: images do not match`。

**解决**：`merge_images_vertical()` 中统一做 `img.convert("RGB")` 转换后再粘贴。同步处理潜在的宽度差异：取组内最大宽度建画布，每张图水平居中。

### 6. `-l` 可选数值参数的解析

**现象**：`-l` 后面可能跟数字（如 `-l 2`），也可能直接跟文件名（如 `-l mydoc.pdf`）。需要区分两种情况。

**原因**：这是一个"可选值"的标志参数，不是标准的 argparse 模式。Python 标准库没有直接支持。

**解决**：手动解析——找到 `-l` 的位置并移除，然后检查当前位置的元素是否为纯数字且在 1-4 范围内。如果是则消费该数字，否则使用默认值 4。关键：判断条件是 `argv[idx].isdigit()` 而非 `argv[idx].isnumeric()`，因为文件名通常不全是数字，即使遇到纯数字文件名也无法与合法 N 值区分——但实际场景中纯数字 PDF 文件名极少见，且用户可明确写 `-l 4` 来消除歧义。

## 函数职责划分

| 函数 | 输入 | 输出 | 说明 |
|---|---|---|---|
| `validate_pdf()` | 文件路径 | `Document \| None` | 失败不退出，返回 None 由上层处理 |
| `pixmap_to_pil()` | `fitz.Pixmap` | `PIL.Image` | 色彩空间归一化，CMYK→sRGB |
| `render_page_to_pil()` | Document + 页索引 | `PIL.Image` | 单页渲染，不写盘 |
| `render_page_to_png()` | Document + 页索引 + 输出目录 | PNG 路径 | 封装渲染+写盘，供逐页模式用 |
| `merge_images_vertical()` | `list[PIL.Image]` | `PIL.Image` | 纵向拼接，处理宽度差异和色彩模式 |
| `zip_pngs()` | PNG 目录 + ZIP 路径 | `bool` | 打包 |
| `convert_one()` | PDF 路径 + 选项 | `(bool, str)` | 单文件全流程，内部按模式分支 |
| `expand_globs()` | 参数列表 | 展开后的列表 | 通配符匹配 |
| `parse_args()` | `sys.argv[1:]` | `(zip, merge, files, dir)` | 参数解析总入口 |

## 经验要点

- Windows 下 Python CLI 工具应优先考虑 GBK/UTF-8 编码兼容，emoji 和特殊字符需慎用或配合编码重配置。
- 通配符展开和参数解析的顺序很重要：**先做类型区分（目录/文件），再做模式展开**。
- tqdm 在 PowerShell 下需显式指定 `file=sys.stdout`，避免 stderr 触发误报。
- 包命名冲突（如 fitz）在 Python 生态中不罕见，优先查是否有别名导入路径（pymupdf）。
- PIL 图片拼接前务必统一色彩模式（`.convert("RGB")`），否则 `paste()` 会因 RGBA/RGB 不匹配报错。
- 可选值标志参数（如 `-l [N]`）无法用 argparse 简洁表达，手动 `index()` + `isdigit()` 解析更灵活可控。
- 渲染函数按"获取数据"和"写入磁盘"拆分（`render_page_to_pil` vs `render_page_to_png`），让合并模式能复用渲染逻辑而无需写中间文件。
