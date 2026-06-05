# pdf2png

轻量化 PDF 转 PNG 命令行工具。将 PDF 每一页渲染为 PNG 图片，可选择打包为 ZIP 文件，支持批量处理。

## 用法

```powershell
pdf2png [-z] <pdf_file> [pdf_file2 ...] [save_path]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `-z` | 否 | 将 PNG 图片打包为 `<pdf文件名>.zip`，默认不打包 |
| `pdf_file` | 是 | 待转换的 PDF 文件路径（可多个） |
| `save_path` | 否 | 输出目录（必须是已存在的目录），默认为当前目录 |

### 示例

```powershell
# 单个文件，输出到当前目录下的 mydoc/ 文件夹
pdf2png mydoc.pdf

# 单个文件，打包为 ZIP
pdf2png -z mydoc.pdf

# 批量处理多个文件
pdf2png doc1.pdf doc2.pdf doc3.pdf

# 通配符：转换当前目录下所有 PDF
pdf2png ./*.pdf
pdf2png *.pdf

# 通配符：转换特定前缀的 PDF
pdf2png report*.pdf

# 批量处理并打包
pdf2png -z doc1.pdf doc2.pdf

# 指定输出目录（必须是已存在的目录路径）
pdf2png doc1.pdf doc2.pdf D:\output
pdf2png ./*.pdf D:\output
```

## 输出

- **默认**：在目标路径下创建 `<pdf文件名>/` 文件夹，内含 `<pdf文件名>_1.png`, `<pdf文件名>_2.png`, ...
- **-z 模式**：以上 PNG 文件打包为 `<pdf文件名>.zip`，中间 PNG 自动清理
- 批量处理时遇到错误文件不会中断，最后会输出成功/失败汇总

## 安装

将 `d:\Tools` 加入系统 PATH 环境变量即可在任意目录使用 `pdf2png` 命令。

```powershell
# 用户级（无需管理员权限）
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";d:\Tools", "User")
```

## 依赖

- Python 3.8+
- PyMuPDF (fitz) — PDF 渲染
- Pillow — 图片处理
- tqdm — 进度条

```powershell
pip install -r ..\requirements.txt
```

## 项目结构

```
d:\Tools\
  pdf2png.cmd           # 命令行入口（cmd / PowerShell 通用）
  pdf2png\              # 项目目录
    pdf2png.py          # 核心脚本
    README.md           # 本文档
```
