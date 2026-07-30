"""
MyBooks Book Source — 独立 CLI 版

用法:
    main.py search <关键词> [--source 书源文件] [--json]
    main.py info <bookUrl> [--source 书源文件]
    main.py toc <bookUrl> [--source 书源文件]
    main.py epub <关键词> [--max 章节数] [--source 书源文件] [--output 路径]
    main.py sources [--source 书源文件]
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def _resource_path(rel):
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)

DEFAULT_SOURCE = _resource_path("sources.json")


def load_source(source_path, index=0):
    from book_source_model import load_sources_from_json
    if not os.path.exists(source_path):
        logger.error("书源文件不存在: %s", source_path)
        sys.exit(1)
    sources = load_sources_from_json(source_path)
    if not sources:
        logger.error("书源文件为空")
        sys.exit(1)
    return sources[index]


def cmd_search(args):
    from rule_engine import search_books
    source = load_source(args.source, args.source_index)
    logger.info("书源: %s | 搜索: %s", source.bookSourceName, args.keyword)
    results = search_books(source, args.keyword)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("未找到结果")
            return
        for i, b in enumerate(results, 1):
            print(f"{i:3d}. {b.get('name','?'):25s} {b.get('author','?'):15s} {b.get('bookUrl','')}")
    return results


def cmd_info(args):
    from rule_engine import fetch_book_info
    source = load_source(args.source, args.source_index)
    detail = fetch_book_info(source, args.bookUrl)
    if args.json:
        print(json.dumps(detail or {}, ensure_ascii=False, indent=2))
    else:
        if not detail:
            print("未获取到详情")
            return
        for k, v in detail.items():
            print(f"{k}: {v}")


def cmd_toc(args):
    from rule_engine import fetch_toc
    source = load_source(args.source, args.source_index)
    toc = fetch_toc(source, args.bookUrl)
    if args.json:
        print(json.dumps(toc, ensure_ascii=False, indent=2))
    else:
        if not toc:
            print("未获取到目录")
            return
        for i, ch in enumerate(toc, 1):
            print(f"{i:4d}. {ch.get('title','?')}")


def cmd_epub(args):
    from rule_engine import search_books, fetch_book_info, fetch_toc, fetch_content
    from epub_helper import generate_epub
    import re

    source = load_source(args.source, args.source_index)
    logger.info("书源: %s | 搜索: %s", source.bookSourceName, args.keyword)

    results = search_books(source, args.keyword)
    if not results:
        logger.error("未搜索到结果")
        sys.exit(1)

    book = results[0]
    logger.info("找到: %s — %s", book.get("name", "?"), book.get("author", "?"))

    detail = fetch_book_info(source, book.get("bookUrl", ""))
    toc = fetch_toc(source, book.get("bookUrl", ""))
    if not toc:
        logger.error("无法获取目录")
        sys.exit(1)

    logger.info("目录: %d 章", len(toc))

    to_download = toc[:args.max_chapters]
    chapters = []
    for i, entry in enumerate(to_download, 1):
        title = entry.get("title", f"第{i}章")
        url = entry.get("url", "")
        logger.info("下载中 [%d/%d]: %s", i, len(to_download), title)
        content = fetch_content(source, url, title)
        if content:
            chapters.append({"title": title, "content": content, "url": url})
        else:
            logger.warning("跳过: %s (内容为空)", title)

    if not chapters:
        logger.error("无有效章节内容")
        sys.exit(1)

    safe_name = re.sub(r'[\\/:*?"<>|]', '_', book.get("name", args.keyword))
    output = args.output or f"{safe_name}.epub"
    cover_url = detail.get("coverUrl", "") if detail else ""

    result = generate_epub(
        title=book.get("name", args.keyword),
        author=book.get("author", "未知"),
        chapters=chapters,
        cover_url=cover_url,
        output_path=output,
    )
    logger.info("EPUB 已生成: %s", result)


def cmd_sources(args):
    from book_source_model import load_sources_from_json
    if not os.path.exists(args.source):
        logger.error("文件不存在: %s", args.source)
        sys.exit(1)
    sources = load_sources_from_json(args.source)
    for i, s in enumerate(sources):
        print(f"{i:3d}. {s.bookSourceName:30s} {s.bookSourceUrl}")


def main():
    parser = argparse.ArgumentParser(description="MyBooks Book Source CLI")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help=f"书源 JSON 文件 (默认: {DEFAULT_SOURCE})")
    parser.add_argument("--source-index", type=int, default=0, help="使用第几个书源 (默认: 0)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="搜索书籍")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--json", action="store_true", help="JSON 格式输出")

    p_info = sub.add_parser("info", help="获取书籍详情")
    p_info.add_argument("bookUrl", help="书籍详情页 URL")
    p_info.add_argument("--json", action="store_true", help="JSON 格式输出")

    p_toc = sub.add_parser("toc", help="获取目录")
    p_toc.add_argument("bookUrl", help="书籍详情页 URL")
    p_toc.add_argument("--json", action="store_true", help="JSON 格式输出")

    p_epub = sub.add_parser("epub", help="搜索并生成 EPUB")
    p_epub.add_argument("keyword", help="搜索关键词")
    p_epub.add_argument("--max", dest="max_chapters", type=int, default=9999, help="最大章节数")
    p_epub.add_argument("--output", help="EPUB 输出路径")

    p_sources = sub.add_parser("sources", help="列出可用书源")

    args = parser.parse_args()

    if args.command == "search":
        cmd_search(args)
    elif args.command == "info":
        cmd_info(args)
    elif args.command == "toc":
        cmd_toc(args)
    elif args.command == "epub":
        cmd_epub(args)
    elif args.command == "sources":
        cmd_sources(args)


if __name__ == "__main__":
    main()
