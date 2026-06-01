#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf2png - 轻量化 PDF 转 PNG 工具
将 PDF 文件的每一页渲染为 PNG 图片，可选打包为 ZIP 文件或合并为长图，支持批量处理。

用法: pdf2png [-z] [-l [N]] <pdf_file> [pdf_file2 ...] [save_path]

选项:
  -z         将 PNG 图片打包为 <pdf文件名>.zip（默认不打包）
  -l [N]     将每 N 页纵向合并为一张长图，N 范围 1-4（默认 4）
             不足 N 页的尾部合并为一张

输出:
  默认:      在目标路径下创建 <pdf文件名>/ 文件夹，内含 <pdf文件名>_1.png, ...
  -l 模式:   合并长图，命名为 <pdf文件名>_1-4.png, <pdf文件名>_5-8.png, ...
  -z 模式:   打包为 <pdf文件名>.zip，中间 PNG 自动清理
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
RENDER_DPI = 200           # 渲染分辨率（每英寸像素数），平衡清晰度和文件大小
DEFAULT_MERGE_COUNT = 4    # -l 默认每组合并页数


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


def pixmap_to_pil(pix: fitz.Pixmap) -> Image.Image:
    """将 fitz.Pixmap 转换为 PIL Image，自动处理色彩空间。

    支持的色彩空间：RGB、RGBA、CMYK（自动转 sRGB）、灰度。
    """
    # CMYK 需先转换为 sRGB
    if pix.n == 4 and not pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    # 根据通道数确定 PIL 图像模式
    if pix.n == 4:
        mode = "RGBA"
    elif pix.n == 3:
        mode = "RGB"
    elif pix.n == 1:
        mode = "L"  # 灰度
    else:
        mode = "RGB"

    return Image.frombytes(mode, [pix.width, pix.height], pix.samples)


def render_page_to_pil(doc: fitz.Document, page_index: int) -> Image.Image:
    """渲染 PDF 某一页为 PIL Image 对象（不写入磁盘）。"""
    page = doc[page_index]
    pix = page.get_pixmap(dpi=RENDER_DPI)
    return pixmap_to_pil(pix)


def render_page_to_png(doc: fitz.Document, page_index: int, output_dir: str, basename: str) -> str:
    """渲染 PDF 的某一页并保存为 PNG 文件。

    Returns:
        生成的 PNG 文件的完整路径

    命名规则: <basename>_<page_index + 1>.png（页码 1 起始）
    """
    page_num = page_index + 1
    png_name = f"{basename}_{page_num}.png"
    png_path = os.path.join(output_dir, png_name)

    img = render_page_to_pil(doc, page_index)
    img.save(png_path, "PNG")
    return png_path


def merge_images_vertical(images: list[Image.Image]) -> Image.Image:
    """将多张 PIL Image 纵向拼接为一张长图。

    以最大宽度为画布宽度，每张图片水平居中；
    背景用白色填充，处理不同色彩模式（RGBA→RGB）。

    Returns:
        拼接后的 PIL Image（RGB 模式）
    """
    if not images:
        raise ValueError("图片列表不能为空")

    max_width = max(img.width for img in images)
    total_height = sum(img.height for img in images)

    canvas = Image.new("RGB", (max_width, total_height), (255, 255, 255))

    y_offset = 0
    for img in images:
        # 统一转为 RGB 后再粘贴
        if img.mode != "RGB":
            img = img.convert("RGB")
        x_offset = (max_width - img.width) // 2
        canvas.paste(img, (x_offset, y_offset))
        y_offset += img.height

    return canvas


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


def convert_one(
    pdf_path: str,
    save_dir: str,
    do_zip: bool,
    merge_count: int = 0,
    file_index: int = 0,
    total_files: int = 1,
) -> tuple[bool, str]:
    """转换单个 PDF 文件。

    Args:
        pdf_path: PDF 文件路径
        save_dir: 输出目录
        do_zip: 是否打包为 ZIP
        merge_count: 每组合并页数，0 或 1 表示不合并不合并（逐页输出）
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
        return (False, "无法打开文件")

    basename = Path(pdf_path).stem
    page_count = len(doc)
    do_merge = merge_count > 1  # 是否启用长图合并模式

    # 确保输出目录可写
    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as e:
        doc.close()
        print(f"  错误：无法创建输出目录 {save_dir} ({e})", file=sys.stderr)
        return (False, "无法创建输出目录")

    # 根据是否打包决定输出目录
    if do_zip:
        png_output_dir = tempfile.mkdtemp(prefix="pdf2png_")
    else:
        png_output_dir = os.path.join(save_dir, basename)
        try:
            os.makedirs(png_output_dir, exist_ok=True)
        except OSError as e:
            doc.close()
            print(f"  错误：无法创建输出目录 {png_output_dir} ({e})", file=sys.stderr)
            return (False, "无法创建输出目录")

    output_path = ""
    success = True
    failed_page = 0

    try:
        with tqdm(
            total=page_count,
            desc="  渲染页面",
            unit="页",
            ncols=80,
            ascii=False,
            file=sys.stdout,
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} 页 [{elapsed}<{remaining}]",
        ) as pbar:

            if do_merge:
                # ---- 长图合并模式 ----
                group: list[Image.Image] = []  # 当前组内页面的 PIL Image
                group_start_idx = 0            # 当前组的起始页索引（0 起始）

                for i in range(page_count):
                    try:
                        img = render_page_to_pil(doc, i)
                    except Exception as e:
                        failed_page = i + 1
                        print(f"\n  错误：无法渲染第 {failed_page} 页 ({e})", file=sys.stderr)
                        success = False
                        break
                    group.append(img)

                    # 凑满一组或到达最后一页时，合并并写出
                    if len(group) == merge_count or i == page_count - 1:
                        start_page = group_start_idx + 1  # 1 起始
                        end_page = i + 1
                        # 文件名：单页用 "_N.png"，多页用 "_N-M.png"
                        if start_page == end_page:
                            png_name = f"{basename}_{start_page}.png"
                        else:
                            png_name = f"{basename}_{start_page}-{end_page}.png"
                        png_path = os.path.join(png_output_dir, png_name)

                        merged = merge_images_vertical(group)
                        merged.save(png_path, "PNG")

                        group = []
                        group_start_idx = i + 1

                    pbar.update(1)

            else:
                # ---- 逐页模式 ----
                for i in range(page_count):
                    try:
                        render_page_to_png(doc, i, png_output_dir, basename)
                    except Exception as e:
                        failed_page = i + 1
                        print(f"\n  错误：无法渲染第 {failed_page} 页 ({e})", file=sys.stderr)
                        success = False
                        break
                    pbar.update(1)

        if not success:
            return (False, f"渲染第 {failed_page} 页时失败")

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
        doc.close()
        if do_zip:
            shutil.rmtree(png_output_dir, ignore_errors=True)

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


def parse_args(argv: list[str]) -> tuple[bool, int, list[str], str]:
    """解析命令行参数，支持通配符展开。

    Returns:
        (do_zip, merge_count, pdf_files, save_dir)
    """
    do_zip = False
    if "-z" in argv:
        do_zip = True
        argv.remove("-z")

    # 解析 -l [N]（N 范围 1-4，省略时默认 4）
    merge_count = 0
    if "-l" in argv:
        idx = argv.index("-l")
        argv.pop(idx)
        # 尝试读取紧跟的数字
        if idx < len(argv) and argv[idx].isdigit():
            n = int(argv.pop(idx))
            if 1 <= n <= 4:
                merge_count = n
            else:
                print("错误：-l 参数值必须为 1-4", file=sys.stderr)
                sys.exit(1)
        else:
            merge_count = DEFAULT_MERGE_COUNT

    if len(argv) < 1:
        print("用法: pdf2png [-z] [-l [N]] <pdf_file> [pdf_file2 ...] [save_path]", file=sys.stderr)
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

    return do_zip, merge_count, pdf_args, save_dir


def main():
    do_zip, merge_count, pdf_files, save_dir = parse_args(sys.argv[1:])
    total = len(pdf_files)

    results: list[tuple[str, bool, str]] = []  # (文件名, 成功, 输出路径/错误)

    for idx, pdf_path in enumerate(pdf_files, start=1):
        ok, output = convert_one(
            pdf_path, save_dir, do_zip,
            merge_count=merge_count,
            file_index=idx, total_files=total,
        )
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
