#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 Markdown 文件中的飞书(Feishu/Lark)图片下载链接转换为本地图片。

用法:
    # 处理单个文件
    python download_feishu_images.py notes.md

    # 批量处理多个文件 (支持 glob 通配符)
    python download_feishu_images.py "*.md"
    python download_feishu_images.py "docs/*.md" "更多笔记/*.md"

可选参数:
    -d / --img-dir   图片保存目录名 (默认: images，建在每个 md 文件同级目录下)
    --suffix         输出文件名后缀 (默认: _local，即 notes.md -> notes_local.md)
    --in-place       直接修改原文件，不生成新文件（谨慎使用，建议先不加这个参数跑一次确认效果）
    --dry-run        只提取链接并打印，不实际下载、不写文件
"""

import argparse
import glob
import os
import re
import sys
import time
import hashlib
from urllib.parse import urlparse

import urllib.request
import urllib.error

# 匹配 markdown 图片语法: ![alt](url) 或 ![alt](url "title")
# 只匹配飞书相关域名的链接，避免误伤其他图片
MD_IMAGE_PATTERN = re.compile(
    r'!\[([^\]]*)\]\(\s*(https?://[^\s)]+(?:feishu\.cn|larksuite\.com|lark-oapi)[^\s)]*)\s*(?:"[^"]*")?\s*\)'
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://www.feishu.cn/",
}


def guess_extension(url, content_type):
    """尝试从 URL 或响应的 Content-Type 猜测图片后缀名"""
    path = urlparse(url).path
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        if path.lower().endswith(ext):
            return ext

    if content_type:
        content_type = content_type.split(";")[0].strip().lower()
        mapping = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }
        if content_type in mapping:
            return mapping[content_type]

    return ".png"


def download_image(url, timeout=20, retries=3):
    """下载单张图片，返回 (bytes, content_type)。失败抛异常。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if content_type and "text/html" in content_type.lower():
                    raise ValueError(
                        "返回的是 HTML 页面而不是图片，链接可能已过期或无权限访问"
                    )
                if len(data) < 100:
                    raise ValueError("返回内容过小，疑似无效响应")
                return data, content_type
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
            continue
    raise RuntimeError(f"下载失败: {url}\n  原因: {last_err}")


def process_file(md_path, img_dir_name, suffix, in_place, dry_run):
    print(f"\n📄 处理文件: {md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    matches = list(MD_IMAGE_PATTERN.finditer(content))
    if not matches:
        print("  ⚠️  未找到飞书图片链接，跳过")
        return

    print(f"  🔍 找到 {len(matches)} 个飞书图片链接")

    if dry_run:
        for i, m in enumerate(matches, 1):
            alt, url = m.group(1), m.group(2)
            print(f"    [{i}] alt='{alt}'  url={url[:80]}...")
        return

    md_dir = os.path.dirname(os.path.abspath(md_path))
    img_dir_abs = os.path.join(md_dir, img_dir_name)
    os.makedirs(img_dir_abs, exist_ok=True)

    url_to_local = {}
    new_content = content
    success, failed = 0, 0
    failed_list = []

    for i, m in enumerate(matches, 1):
        alt, url = m.group(1), m.group(2)
        full_match = m.group(0)

        if url in url_to_local:
            local_rel_path = url_to_local[url]
        else:
            print(f"    [{i}/{len(matches)}] 下载中: {url[:90]}...")
            try:
                data, content_type = download_image(url)
            except RuntimeError as e:
                print(f"      ❌ {e}")
                failed += 1
                failed_list.append(url)
                continue

            ext = guess_extension(url, content_type)
            short_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
            base_name = os.path.splitext(os.path.basename(md_path))[0]
            filename = f"{base_name}_img_{i:03d}_{short_hash}{ext}"
            filepath = os.path.join(img_dir_abs, filename)

            with open(filepath, "wb") as imgf:
                imgf.write(data)

            local_rel_path = os.path.join(img_dir_name, filename).replace("\\", "/")
            url_to_local[url] = local_rel_path
            success += 1
            print(f"      ✅ 已保存为 {local_rel_path}")

        new_image_md = f"![{alt}]({local_rel_path})"
        new_content = new_content.replace(full_match, new_image_md, 1)

    if in_place:
        output_path = md_path
    else:
        base, ext = os.path.splitext(md_path)
        output_path = f"{base}{suffix}{ext}"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  ✅ 成功: {success} 张" + (f" | ❌ 失败: {failed} 张" if failed else ""))
    if failed_list:
        for u in failed_list:
            print(f"     - {u}")
    print(f"  📄 输出文件: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="把 Markdown 中的飞书图片链接下载为本地图片（支持批量/通配符）")
    parser.add_argument("patterns", nargs="+", help="markdown 文件路径或通配符，如 notes.md 或 \"*.md\"")
    parser.add_argument("-d", "--img-dir", default="images", help="图片保存目录名（默认 images）")
    parser.add_argument("--suffix", default="_local", help="输出文件名后缀（默认 _local）")
    parser.add_argument("--in-place", action="store_true", help="直接覆盖原文件，不生成新文件")
    parser.add_argument("--dry-run", action="store_true", help="只提取并打印链接，不下载、不写文件")
    args = parser.parse_args()

    # 展开所有 glob 通配符，并去重、排序
    files = set()
    for pattern in args.patterns:
        matched = glob.glob(pattern)
        if not matched and os.path.isfile(pattern):
            matched = [pattern]
        files.update(matched)

    files = sorted(f for f in files if f.lower().endswith(".md"))

    if not files:
        print(f"❌ 没有匹配到任何 .md 文件: {args.patterns}")
        sys.exit(1)

    print(f"📚 共匹配到 {len(files)} 个 markdown 文件:")
    for f in files:
        print(f"   - {f}")

    for md_path in files:
        process_file(md_path, args.img_dir, args.suffix, args.in_place, args.dry_run)

    print("\n" + "=" * 50)
    print("🎉 全部处理完成" + ("（dry-run，未修改任何文件）" if args.dry_run else ""))
    print("=" * 50)


if __name__ == "__main__":
    main()