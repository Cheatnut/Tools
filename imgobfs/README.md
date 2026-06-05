# imgobfs

小番茄风格图片混淆/解混淆命令行工具。对 PNG/JPG 图片进行分块置乱+像素异或的双重混淆，可完全可逆还原。

## 算法原理

```
混淆:  原图 → [分块] → [块内 XOR] → [块置换] → 混淆图(PNG)
解混淆: 混淆图 → [逆块置换] → [块内 XOR] → [去填充] → 原图(PNG)
```

1. **分块**：将图片划分为 B×B 像素方块，边缘镜像填充补齐
2. **块内 XOR**：每个块内像素用独立种子做异或运算
3. **块置换**：Fisher-Yates 固定种子洗牌打乱块排列
4. **解混淆**：上述操作的逆过程，原图尺寸记录在 PNG 元数据中

整个过程由固定种子决定，无需输入密钥。

## 用法

```powershell
imgobfs [-d] [-b N] <image_file> [image_file2 ...] [save_path]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `-d` | 否 | 解混淆模式（默认是混淆模式） |
| `-b N` | 否 | 分块大小，范围 32-128，默认 64 |
| `image_file` | 是 | 待处理的图片文件（支持 png/jpg/jpeg/bmp），可多个 |
| `save_path` | 否 | 输出目录（已存在的目录），默认当前目录 |

### 示例

```powershell
# 混淆单个图片
imgobfs photo.png

# 解混淆
imgobfs -d photo_obfs.png

# 指定块大小（越小的块混淆效果越好，但处理越慢）
imgobfs -b 32 photo.jpg

# 批量混淆
imgobfs ./*.png

# 批量解混淆
imgobfs -d ./*_obfs.png

# 指定输出目录
imgobfs photo.png D:\output
```

## 输出

- **混淆模式**：`<原文件名>_obfs.png`（始终输出 PNG，保证无损）
- **解混淆模式**：`<原文件名>_restored.png`
- 批量处理时遇到错误不中断，最后输出成功/失败汇总

## 安装

将 `d:\Tools` 加入系统 PATH 环境变量即可在任意目录使用 `imgobfs` 命令。

```powershell
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";d:\Tools", "User")
```

## 依赖

- Python 3.8+
- Pillow — 图片读写和处理
- tqdm — 进度条

```powershell
pip install -r ..\requirements.txt
```

## 项目结构

```
d:\Tools\
  imgobfs.cmd           # 命令行入口（cmd / PowerShell 通用）
  imgobfs\              # 项目目录
    imgobfs.py          # 核心脚本
    README.md           # 本文档
```
