"""
generate_epub — 独立 CLI 封装。

直接从书源搜索书籍并生成 EPUB，不依赖 MyBooks Toolbox。

用法:
    python generate_epub.py <关键词> [最大章节数]
    python generate_epub.py 捞尸人 50

环境变量:
    BOOK_SOURCE_PATH  书源 JSON 文件路径（默认 sample_sources.json）
    CALIBREDB         calibredb 可执行路径（默认 from PATH）
"""

import json
import logging
import os
import re
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_epub.py <关键词> [最大章节数]")
        sys.exit(1)

    keyword = sys.argv[1]
    max_chapters = int(sys.argv[2]) if len(sys.argv) > 2 else 9999

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from rule_engine import search_books, fetch_book_info, fetch_toc, fetch_content
    from epub_helper import generate_epub
    from book_source_model import load_sources_from_json

    sources_path = os.environ.get("BOOK_SOURCE_PATH") or os.path.join(
        os.path.dirname(__file__), "sample_sources.json"
    )
    if not os.path.exists(sources_path):
        logger.error("书源文件不存在: %s", sources_path)
        logger.error("请设置 BOOK_SOURCE_PATH 环境变量指向合法的书源 JSON 文件")
        sys.exit(1)

    sources = load_sources_from_json(sources_path)
    source = sources[0]

    logger.info("书源: %s", source.bookSourceName)
    logger.info("正在搜索: %s", keyword)

    results = search_books(source, keyword)
    if not results:
        logger.error("未搜索到结果")
        sys.exit(1)

    book = results[0]
    logger.info("找到: %s — %s", book.get("name", "?"), book.get("author", "?"))
    logger.info("详情页: %s", book.get("bookUrl", "?"))

    detail = fetch_book_info(source, book.get("bookUrl", ""))
    if detail:
        logger.info("字数: %s", detail.get("wordCount", "?"))
        logger.info("最新章节: %s", detail.get("lastChapter", "?"))

    toc = fetch_toc(source, book.get("bookUrl", ""))
    if not toc:
        logger.error("无法获取目录")
        sys.exit(1)

    logger.info("目录: %d 章", len(toc))

    to_download = toc[:max_chapters]
    chapters = []
    for i, entry in enumerate(to_download, 1):
        ch_title = entry.get("title", f"第{i}章")
        ch_url = entry.get("url", "")
        logger.info("下载中 [%d/%d]: %s", i, len(to_download), ch_title)

        content = fetch_content(source, ch_url, ch_title)
        if content:
            chapters.append({"title": ch_title, "content": content, "url": ch_url})
        else:
            logger.warning("跳过: %s (内容为空)", ch_title)

    if not chapters:
        logger.error("无有效章节内容")
        sys.exit(1)

    safe_name = re.sub(r'[\\/:*?"<>|]', '_', book.get("name", keyword))
    output_path = f"{safe_name}.epub"
    cover_url = detail.get("coverUrl", "") if detail else ""

    result = generate_epub(
        title=book.get("name", keyword),
        author=book.get("author", "未知"),
        chapters=chapters,
        cover_url=cover_url,
        output_path=output_path,
    )
    logger.info("EPUB 已生成: %s", result)

    calibre_bin = os.environ.get("CALIBREDB") or shutil.which("calibredb")
    if calibre_bin and os.path.exists(calibre_bin):
        import subprocess
        try:
            subprocess.run(
                [calibre_bin, "add", result],
                capture_output=True, timeout=30,
            )
            logger.info("已导入 Calibre")
        except Exception as exc:
            logger.info("Calibre 导入跳过: %s", exc)


if __name__ == "__main__":
    main()
