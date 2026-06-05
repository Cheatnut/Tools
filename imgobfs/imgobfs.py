#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
imgobfs - 小番茄风格图片混淆/解混淆工具
对 PNG/JPG 图片进行分块置乱+像素异或的双重混淆，可完全可逆还原。

用法: imgobfs [-d] [-b N] <image_file> [image_file2 ...] [save_path]

选项:
  -d       解混淆模式（默认是混淆模式）
  -b N     分块大小，范围 32-128（默认 64）

输出:
  混淆:  <原文件名>_obfs.png
  解混淆: <原文件名>_restored.png
"""

import glob
import os
import random
import sys

# Windows 终端下强制 UTF-8 输出，避免 GBK 编码报错
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo
from tqdm import tqdm

# ---- 常量 ----
DEFAULT_BLOCK_SIZE = 64        # 默认分块大小（像素）
MIN_BLOCK_SIZE = 32            # 最小分块大小
MAX_BLOCK_SIZE = 128           # 最大分块大小
SHUFFLE_SEED = 0x6A09E667      # 块置换的固定种子
XOR_BASE_SEED = 0xBB67AE85     # 块内 XOR 的基础种子


# =============================================================================
# 算法核心
# =============================================================================

def pad_to_block(img: Image.Image, block_size: int) -> tuple[Image.Image, int, int]:
    """将图片用边缘镜像填充到 block_size 的整数倍。

    返回 (填充后的图片, 原始宽度, 原始高度)。
    解混淆时根据原始尺寸裁剪即可精确还原。
    """
    w, h = img.size
    pad_w = (block_size - w % block_size) % block_size
    pad_h = (block_size - h % block_size) % block_size

    if pad_w == 0 and pad_h == 0:
        return img, w, h

    new_w, new_h = w + pad_w, h + pad_h
    padded = Image.new(img.mode, (new_w, new_h))
    padded.paste(img, (0, 0))

    # 右侧边缘镜像
    if pad_w > 0:
        right_edge = padded.crop((w - 1, 0, w, h))
        for x in range(w, new_w):
            padded.paste(right_edge, (x, 0))

    # 底部边缘镜像
    if pad_h > 0:
        bottom_edge = padded.crop((0, h - 1, new_w, h))
        for y in range(h, new_h):
            padded.paste(bottom_edge, (0, y))

    return padded, w, h


def split_blocks(img: Image.Image, block_size: int) -> list[Image.Image]:
    """将图片分割为 block_size × block_size 的方块列表（按行排列）。"""
    w, h = img.size
    blocks = []
    for y in range(0, h, block_size):
        for x in range(0, w, block_size):
            block = img.crop((x, y, x + block_size, y + block_size))
            blocks.append(block)
    return blocks


def merge_blocks(blocks: list[Image.Image], total_w: int, total_h: int, block_size: int) -> Image.Image:
    """将方块列表按行拼回完整图片。"""
    mode = blocks[0].mode
    result = Image.new(mode, (total_w, total_h))
    cols = total_w // block_size
    for idx, block in enumerate(blocks):
        row = idx // cols
        col = idx % cols
        x = col * block_size
        y = row * block_size
        result.paste(block, (x, y))
    return result


def xor_block(block_img: Image.Image, block_idx: int) -> Image.Image:
    """对块内每个像素的 R/G/B 做 XOR，A 通道保留不变。

    每个块的 XOR 序列由 (XOR_BASE_SEED, block_idx) 联合种子生成，
    不同块有不同的 XOR 模式，增加混淆强度。
    """
    rng = random.Random(XOR_BASE_SEED ^ (block_idx * 0x5BD1E995))
    pixels = block_img.load()
    has_alpha = block_img.mode == "RGBA"

    for y in range(block_img.height):
        for x in range(block_img.width):
            px = pixels[x, y]
            r = px[0] ^ rng.randint(0, 255)
            g = px[1] ^ rng.randint(0, 255)
            b = px[2] ^ rng.randint(0, 255)
            if has_alpha:
                pixels[x, y] = (r, g, b, px[3])
            else:
                pixels[x, y] = (r, g, b)

    return block_img


def get_shuffle_permutation(n: int) -> list[int]:
    """用 Fisher-Yates 生成固定种子的排列表。

    perm[i] = 位置 i 的块来自原始位置 perm[i]。
    """
    rng = random.Random(SHUFFLE_SEED)
    indices = list(range(n))
    for i in range(n - 1, 0, -1):
        j = rng.randint(0, i)
        indices[i], indices[j] = indices[j], indices[i]
    return indices


def invert_permutation(perm: list[int]) -> list[int]:
    """求排列的逆。"""
    inv = [0] * len(perm)
    for i, p in enumerate(perm):
        inv[p] = i
    return inv


def apply_permutation(blocks: list[Image.Image], perm: list[int]) -> list[Image.Image]:
    """按排列表重排方块。"""
    return [blocks[perm[i]] for i in range(len(blocks))]


# =============================================================================
# 混淆 / 解混淆 管线
# =============================================================================

def obfuscate_image(img: Image.Image, block_size: int) -> tuple[Image.Image, int, int]:
    """对图片进行小番茄混淆。

    Returns:
        (混淆后的图片, 原始宽度, 原始高度)
        原始尺寸需随图片保存，供解混淆时裁剪用。
    """
    # 统一为 RGB 或 RGBA，避免调色板模式
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if img.mode == "PA" or "A" in img.mode else "RGB")

    # 填充到块大小的整数倍
    padded, orig_w, orig_h = pad_to_block(img, block_size)
    pad_w, pad_h = padded.size

    # 分块
    blocks = split_blocks(padded, block_size)
    total_blocks = len(blocks)

    # 块内 XOR（每个块独立种子）
    for i in range(total_blocks):
        xor_block(blocks[i], i)

    # 块置换
    perm = get_shuffle_permutation(total_blocks)
    blocks = apply_permutation(blocks, perm)

    # 拼回
    result = merge_blocks(blocks, pad_w, pad_h, block_size)
    return result, orig_w, orig_h


def deobfuscate_image(img: Image.Image, block_size: int, orig_w: int, orig_h: int) -> Image.Image:
    """对小番茄混淆的图片进行解混淆。

    Args:
        img: 混淆后的图片
        block_size: 混淆时使用的分块大小
        orig_w, orig_h: 原始图片尺寸（用于裁剪填充）
    """
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if img.mode == "PA" or "A" in img.mode else "RGB")

    pad_w, pad_h = img.size

    # 分块
    blocks = split_blocks(img, block_size)
    total_blocks = len(blocks)

    # 逆块置换
    perm = get_shuffle_permutation(total_blocks)
    inv_perm = invert_permutation(perm)
    blocks = apply_permutation(blocks, inv_perm)

    # 块内 XOR（XOR 自逆，再做一次即还原）
    for i in range(total_blocks):
        xor_block(blocks[i], i)

    # 拼回
    result = merge_blocks(blocks, pad_w, pad_h, block_size)

    # 裁剪掉填充部分
    result = result.crop((0, 0, orig_w, orig_h))
    return result


# =============================================================================
# PNG 元数据读写（存储原始尺寸）
# =============================================================================

def save_obfs(img: Image.Image, path: str, orig_w: int, orig_h: int) -> None:
    """保存混淆图片，附带原始尺寸元数据。"""
    meta = PngInfo()
    meta.add_text("imgobfs_w", str(orig_w))
    meta.add_text("imgobfs_h", str(orig_h))
    img.save(path, "PNG", pnginfo=meta)


def load_obfs(path: str) -> tuple[Image.Image, int, int, int]:
    """读取混淆图片及其元数据。

    Returns:
        (图片, 原始宽度, 原始高度, 分块大小)
        若非混淆图片（无元数据），orig_w/orig_h 返回 0。
    """
    img = Image.open(path)
    orig_w, orig_h, block_size = 0, 0, 0
    # Pillow 的 text 属性在打开 PNG 后可用
    if hasattr(img, "text") and img.text:
        try:
            orig_w = int(img.text.get("imgobfs_w", 0))
            orig_h = int(img.text.get("imgobfs_h", 0))
        except (ValueError, TypeError):
            pass
    return img, orig_w, orig_h


# =============================================================================
# 单文件处理
# =============================================================================

def process_one(
    image_path: str,
    save_dir: str,
    do_deobfs: bool,
    block_size: int,
    file_index: int = 0,
    total_files: int = 1,
) -> tuple[bool, str]:
    """处理单个图片文件。

    Args:
        image_path: 图片路径
        save_dir: 输出目录
        do_deobfs: True=解混淆, False=混淆
        block_size: 分块大小
        file_index: 当前文件序号（1 起始）
        total_files: 文件总数

    Returns:
        (成功标志, 输出路径或错误描述)
    """
    prefix = f"[{file_index}/{total_files}] " if total_files > 1 else ""
    image_filename = os.path.basename(image_path)
    print(f"{prefix}处理中：{image_filename}")

    # 验证文件存在
    if not os.path.isfile(image_path):
        print(f"  错误：找不到文件 {image_path}", file=sys.stderr)
        return (False, "找不到文件")

    # 确保输出目录可写
    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as e:
        print(f"  错误：无法创建输出目录 {save_dir} ({e})", file=sys.stderr)
        return (False, "无法创建输出目录")

    basename = Path(image_path).stem

    try:
        # 打开图片，统一为 RGB 或 RGBA
        img = Image.open(image_path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode or img.mode == "PA" else "RGB")

        if do_deobfs:
            # ---- 解混淆 ----
            # 从 PNG 元数据读取原始尺寸
            _, orig_w, orig_h = load_obfs(image_path)
            if orig_w == 0 or orig_h == 0:
                print(f"  错误：该图片不含混淆元数据，无法解混淆", file=sys.stderr)
                return (False, "非混淆图片，无法解混淆")

            with tqdm(
                total=1, desc="  解混淆", unit=" 张", ncols=80, ascii=False,
                file=sys.stdout, bar_format="{desc}: {percentage:3.0f}%|{bar}|",
            ) as pbar:
                result = deobfuscate_image(img, block_size, orig_w, orig_h)
                pbar.update(1)

            out_name = f"{basename}_restored.png"
        else:
            # ---- 混淆 ----
            with tqdm(
                total=1, desc="  混淆", unit=" 张", ncols=80, ascii=False,
                file=sys.stdout, bar_format="{desc}: {percentage:3.0f}%|{bar}|",
            ) as pbar:
                result, orig_w, orig_h = obfuscate_image(img, block_size)
                pbar.update(1)

            out_name = f"{basename}_obfs.png"

        img.close()

        out_path = os.path.join(save_dir, out_name)

        if do_deobfs:
            result.save(out_path, "PNG")
        else:
            save_obfs(result, out_path, orig_w, orig_h)

    except Exception as e:
        print(f"  错误：处理失败 ({e})", file=sys.stderr)
        return (False, str(e))

    print(f"  ✓ 完成 → {out_path}")
    return (True, out_path)


# =============================================================================
# 参数解析
# =============================================================================

def expand_globs(args: list[str]) -> list[str]:
    """展开参数中的通配符（*, ?, []）。"""
    result = []
    for arg in args:
        if any(ch in arg for ch in "*?["):
            if os.path.isdir(arg):
                result.append(arg)
                continue
            matches = sorted(glob.glob(arg))
            if matches:
                result.extend(matches)
            else:
                result.append(arg)
        else:
            result.append(arg)
    return result


def parse_args(argv: list[str]) -> tuple[bool, int, list[str], str]:
    """解析命令行参数。

    Returns:
        (do_deobfs, block_size, image_files, save_dir)
    """
    do_deobfs = False
    if "-d" in argv:
        do_deobfs = True
        argv.remove("-d")

    # 解析 -b N（分块大小）
    block_size = DEFAULT_BLOCK_SIZE
    if "-b" in argv:
        idx = argv.index("-b")
        argv.pop(idx)
        if idx < len(argv) and argv[idx].isdigit():
            n = int(argv.pop(idx))
            if MIN_BLOCK_SIZE <= n <= MAX_BLOCK_SIZE:
                block_size = n
            else:
                print(f"错误：分块大小需在 {MIN_BLOCK_SIZE}-{MAX_BLOCK_SIZE} 之间", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"错误：-b 后需要指定分块大小 ({MIN_BLOCK_SIZE}-{MAX_BLOCK_SIZE})", file=sys.stderr)
            sys.exit(1)

    if len(argv) < 1:
        print("用法: imgobfs [-d] [-b N] <image_file> [image_file2 ...] [save_path]", file=sys.stderr)
        sys.exit(1)

    # 在通配符展开前识别 save_dir
    save_dir = os.getcwd()
    image_args = list(argv)

    if len(argv) > 1:
        last = argv[-1]
        has_glob = any(ch in last for ch in "*?[")
        if not has_glob:
            is_dir = os.path.isdir(last)
            has_trailing_sep = last.endswith(("/", "\\"))
            looks_like_path = (
                "." not in os.path.basename(last)
                and ("/" in last or "\\" in last)
            )
            if is_dir or has_trailing_sep or looks_like_path:
                save_dir = last
                image_args = argv[:-1]

    image_args = expand_globs(image_args)

    if len(image_args) == 0:
        print("用法: imgobfs [-d] [-b N] <image_file> [image_file2 ...] [save_path]", file=sys.stderr)
        sys.exit(1)

    return do_deobfs, block_size, image_args, save_dir


# =============================================================================
# 主入口
# =============================================================================

def main():
    do_deobfs, block_size, image_files, save_dir = parse_args(sys.argv[1:])
    total = len(image_files)

    results: list[tuple[str, bool, str]] = []

    for idx, image_path in enumerate(image_files, start=1):
        ok, output = process_one(
            image_path, save_dir, do_deobfs, block_size,
            file_index=idx, total_files=total,
        )
        results.append((os.path.basename(image_path), ok, output))

    # 批量模式汇总
    if total > 1:
        success_count = sum(1 for _, ok, _ in results if ok)
        fail_count = total - success_count
        print()
        print("=" * 50)
        print(f"批量处理完成：成功 {success_count}/{total}，失败 {fail_count}/{total}")
        for name, ok, output in results:
            status = "✓" if ok else "✗"
            print(f"  {status} {name} → {output}")
        print("=" * 50)


if __name__ == "__main__":
    main()
