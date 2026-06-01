#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf2png - 轻量化 PDF 转 PNG 工具
将 PDF 文件的每一页渲染为 PNG 图片，可选打包为 ZIP 文件，支持批量处理。

用法: pdf2png [-z] <pdf_file> [pdf_file2 ...] [save_path]

选项:
  -z    将 PNG 图片打包为 <pdf文件名>.zip（默认不打包）

输出:
  默认:  在目标路径下创建 <pdf文件名>/ 文件夹，内含 <pdf文件名>_1.png, <pdf文件名>_2.png, ...
  -z 模式: 打包为 <pdf文件名>.zip，中间 PNG 自动清理
"""

import glob
import os
import sys

# Windows 终端下强制 UTF-8 输出，避免 GBK 编码报错
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import zipfile
import tempfile
import shutil
from pathlib import Path

import pymupdf as fitz  # PyMuPDF（用 pymupdf 避免与 frontend 包的 fitz 命名冲突）
from PIL import Image
from tqdm import tqdm

# ---- 常量 ----
RENDER_DPI = 200  # 渲染分辨率（每英寸像素数），平衡清晰度和文件大小


def validate_pdf(pdf_path: str) -> fitz.Document | None:
    """验证 PDF 文件并返回 fitz.Document 对象，失败返回 None 并打印错误。"""
    if not os.path.isfile(pdf_path):
        print(f"  错误：找不到文件 {pdf_path}", file=sys.stderr)
        return None

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  错误：无法打开 PDF 文件，文件可能已损坏 ({e})", file=sys.stderr)
        return None

    if len(doc) == 0:
        doc.close()
        print(f"  错误：PDF 文件没有页面", file=sys.stderr)
        return None

    return doc


def render_page_to_png(doc: fitz.Document, page_index: int, output_dir: str, basename: str) -> str:
    """渲染 PDF 的某一页为 PNG 图片。

    Args:
        doc: fitz.Document 对象
        page_index: 页面索引（0 起始，内部使用）
        output_dir: 输出目录路径
        basename: PDF 文件基本名（用于生成 PNG 文件名）

    Returns:
        生成的 PNG 文件的完整路径

    命名规则: <basename>_<page_index + 1>.png（页码 1 起始，便于用户阅读）
    """
    page = doc[page_index]
    page_num = page_index + 1  # 用户可见的页码，从 1 开始
    png_name = f"{basename}_{page_num}.png"
    png_path = os.path.join(output_dir, png_name)

    # 将页面渲染为 pixmap（默认 RGB 色彩空间）
    pix = page.get_pixmap(dpi=RENDER_DPI)

    # 处理不同色彩空间
    if pix.n == 4 and not pix.alpha:
        # CMYK 色彩空间，需先转换为 sRGB
        pix = fitz.Pixmap(fitz.csRGB, pix)

    # 根据通道数确定 PIL 图像模式
    if pix.n == 4:
        mode = "RGBA"  # 有 alpha 通道
    elif pix.n == 3:
        mode = "RGB"
    elif pix.n == 1:
        mode = "L"  # 灰度
    else:
        mode = "RGB"  # 未知色彩空间，默认按 RGB 处理

    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    img.save(png_path, "PNG")

    return png_path


def zip_pngs(png_dir: str, zip_path: str) -> bool:
    """将指定目录中的所有 PNG 文件打包为 ZIP，成功返回 True。"""
    png_files = sorted(Path(png_dir).glob("*.png"))

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for png_file in png_files:
                # arcname 仅保留文件名，不保留临时目录路径
                zf.write(png_file, arcname=png_file.name)
        return True
    except (OSError, PermissionError) as e:
        print(f"  错误：无法创建 ZIP 文件 {zip_path} ({e})", file=sys.stderr)
        return False


def convert_one(pdf_path: str, save_dir: str, do_zip: bool, file_index: int = 0, total_files: int = 1) -> tuple[bool, str]:
    """转换单个 PDF 文件。

    Args:
        pdf_path: PDF 文件路径
        save_dir: 输出目录
        do_zip: 是否打包为 ZIP
        file_index: 当前文件序号（1 起始，用于批量显示）
        total_files: 文件总数

    Returns:
        (成功标志, 输出路径或错误描述)
    """
    # 构建批量前缀（单文件时不显示序号）
    if total_files > 1:
        prefix = f"[{file_index}/{total_files}] "
    else:
        prefix = ""

    # 验证并打开 PDF
    pdf_filename = os.path.basename(pdf_path)
    print(f"{prefix}转换中：{pdf_filename}")

    doc = validate_pdf(pdf_path)
    if doc is None:
        return (False, f"无法打开文件")

    basename = Path(pdf_path).stem
    page_count = len(doc)

    # 确保输出目录可写
    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as e:
        doc.close()
        print(f"  错误：无法创建输出目录 {save_dir} ({e})", file=sys.stderr)
        return (False, f"无法创建输出目录")

    # 根据是否打包决定输出目录：打包用临时目录，不打包则在 save_dir 下建立同名文件夹
    if do_zip:
        png_output_dir = tempfile.mkdtemp(prefix="pdf2png_")
    else:
        png_output_dir = os.path.join(save_dir, basename)
        try:
            os.makedirs(png_output_dir, exist_ok=True)
        except OSError as e:
            doc.close()
            print(f"  错误：无法创建输出目录 {png_output_dir} ({e})", file=sys.stderr)
            return (False, f"无法创建输出目录")

    output_path = ""  # 最终输出路径，用于完成提示
    success = True

    try:
        # 逐页渲染 PNG，显示进度条
        with tqdm(
            total=page_count,
            desc=f"  渲染页面",
            unit="页",
            ncols=80,
            ascii=False,
            file=sys.stdout,
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} 页 [{elapsed}<{remaining}]",
        ) as pbar:
            for i in range(page_count):
                try:
                    render_page_to_png(doc, i, png_output_dir, basename)
                except Exception as e:
                    print(f"\n  错误：无法渲染第 {i + 1} 页 ({e})", file=sys.stderr)
                    success = False
                    break
                pbar.update(1)

        if not success:
            return (False, f"渲染第 {i + 1} 页时失败")

        # 如果指定了 -z，打包为 ZIP
        if do_zip:
            zip_name = f"{basename}.zip"
            zip_path = os.path.join(save_dir, zip_name)
            if zip_pngs(png_output_dir, zip_path):
                output_path = zip_path
            else:
                return (False, "无法创建 ZIP 文件")
        else:
            output_path = png_output_dir

    finally:
        # 清理资源
        doc.close()
        if do_zip:
            shutil.rmtree(png_output_dir, ignore_errors=True)

    # 完成提示
    print(f"  ✓ 转换完成 → {output_path}")
    return (True, output_path)


def expand_globs(args: list[str]) -> list[str]:
    """展开参数中的通配符（*, ?, [])。

    Windows 下 cmd.exe 不会自动展开通配符，需手动 glob。
    PowerShell 通常会自动展开，因此 glob 不匹配时返回原参数。
    """
    result = []
    for arg in args:
        if any(ch in arg for ch in "*?["):
            # 如果参数已是存在的路径（目录或以路径分隔符结尾），不展开
            if os.path.isdir(arg):
                result.append(arg)
                continue
            matches = sorted(glob.glob(arg))
            if matches:
                result.extend(matches)
            else:
                # 无匹配时保留原参数，后续 validate_pdf 会报"找不到文件"
                result.append(arg)
        else:
            result.append(arg)
    return result


def parse_args(argv: list[str]) -> tuple[bool, list[str], str]:
    """解析命令行参数，支持通配符展开。

    Returns:
        (do_zip, pdf_files, save_dir)
    """
    do_zip = False
    if "-z" in argv:
        do_zip = True
        argv.remove("-z")

    if len(argv) < 1:
        print("用法: pdf2png [-z] <pdf_file> [pdf_file2 ...] [save_path]", file=sys.stderr)
        sys.exit(1)

    # 先在原始参数中识别 save_dir（通配符展开之前），避免展开后误判
    save_dir = os.getcwd()
    pdf_args = list(argv)

    if len(argv) > 1:
        last = argv[-1]
        has_glob = any(ch in last for ch in "*?[")
        if not has_glob:
            # 符合以下任一条件即视为输出目录：
            #   1. 已是存在的目录
            #   2. 以路径分隔符结尾（明确表示这是目录）
            #   3. 不含文件扩展名特征（无 "."），且包含路径分隔符
            is_dir = os.path.isdir(last)
            has_trailing_sep = last.endswith(("/", "\\"))
            looks_like_path = (
                "." not in os.path.basename(last)
                and ("/" in last or "\\" in last)
            )
            if is_dir or has_trailing_sep or looks_like_path:
                save_dir = last
                pdf_args = argv[:-1]

    # 通配符展开（cmd.exe 不会自动展开 *.pdf）
    pdf_args = expand_globs(pdf_args)

    if len(pdf_args) == 0:
        print("用法: pdf2png [-z] <pdf_file> [pdf_file2 ...] [save_path]", file=sys.stderr)
        sys.exit(1)

    return do_zip, pdf_args, save_dir


def main():
    do_zip, pdf_files, save_dir = parse_args(sys.argv[1:])
    total = len(pdf_files)

    results: list[tuple[str, bool, str]] = []  # (文件名, 成功, 输出路径/错误)

    for idx, pdf_path in enumerate(pdf_files, start=1):
        ok, output = convert_one(pdf_path, save_dir, do_zip, file_index=idx, total_files=total)
        results.append((os.path.basename(pdf_path), ok, output))

    # 批量模式（多于 1 个文件）时输出汇总
    if total > 1:
        success_count = sum(1 for _, ok, _ in results if ok)
        fail_count = total - success_count
        print()
        print("=" * 50)
        print(f"批量转换完成：成功 {success_count}/{total}，失败 {fail_count}/{total}")
        for name, ok, output in results:
            status = "✓" if ok else "✗"
            print(f"  {status} {name} → {output}")
        print("=" * 50)


if __name__ == "__main__":
    main()
