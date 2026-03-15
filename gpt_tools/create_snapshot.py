#!/usr/bin/env python3
# scripts/create_snapshot.py

import os
import sys
import ast
import io
import tokenize
import argparse
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("snapshot")


def remove_invisible_spaces(text: str) -> Tuple[str, int]:
    count = text.count("\u00a0") + text.count("\xa0")
    return text.replace("\u00a0", " ").replace("\xa0", " "), count


def is_probable_docstring_node(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    value = node.value
    if isinstance(value, ast.Str):
        return True
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return True
    return False


def collect_python_ranges(tree: ast.AST) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    返回:
    - docstring 行区间列表 [(start, end), ...]
    - print 调用行区间列表 [(start, end), ...]
    """
    docstring_ranges: List[Tuple[int, int]] = []
    print_ranges: List[Tuple[int, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and len(body) > 0 and is_probable_docstring_node(body[0]):
                first = body[0]
                start = getattr(first, "lineno", None)
                end = getattr(first, "end_lineno", start)
                if start is not None:
                    docstring_ranges.append((start, end))

        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "print":
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", start)
                if start is not None:
                    print_ranges.append((start, end))

    return docstring_ranges, print_ranges


def build_line_skip_set(ranges: List[Tuple[int, int]]) -> Set[int]:
    skip: Set[int] = set()
    for start, end in ranges:
        for i in range(start, end + 1):
            skip.add(i)
    return skip


def strip_python_comments(source: str) -> Tuple[str, int]:
    """
    用 tokenize 精准移除 Python 注释，避免误伤字符串里的 #。
    """
    out_tokens = []
    removed = 0

    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            tok_type = tok.type
            tok_str = tok.string

            if tok_type == tokenize.COMMENT:
                removed += 1
                continue

            out_tokens.append(tok)

        cleaned = tokenize.untokenize(out_tokens)
        return cleaned, removed
    except tokenize.TokenError:
        # tokenize 失败时降级：仅删除整行注释
        lines = source.splitlines()
        kept = []
        for line in lines:
            if line.strip().startswith("#"):
                removed += 1
                continue
            kept.append(line)
        return "\n".join(kept), removed


def remove_blank_lines(text: str) -> Tuple[str, int]:
    lines = text.splitlines()
    cleaned_lines = []
    removed = 0

    for line in lines:
        if line.strip() == "":
            removed += 1
            continue
        cleaned_lines.append(line.rstrip())

    return "\n".join(cleaned_lines), removed


def clean_python_content(original_content: str) -> Tuple[str, int, int]:
    """
    返回:
    cleaned_text, removed_count, fixed_spaces_count
    """
    text, fixed_spaces = remove_invisible_spaces(original_content)
    removed_count = 0

    try:
        tree = ast.parse(text)
        docstring_ranges, print_ranges = collect_python_ranges(tree)
        skip_lines = build_line_skip_set(docstring_ranges + print_ranges)

        lines = text.splitlines()
        kept_lines = []
        for i, line in enumerate(lines, start=1):
            if i in skip_lines:
                removed_count += 1
                continue
            kept_lines.append(line)

        text = "\n".join(kept_lines)

    except SyntaxError:
        logger.warning("解析 Python AST 失败，跳过 docstring/print AST 清理，仅做注释和空行清理。")

    text, comments_removed = strip_python_comments(text)
    removed_count += comments_removed

    text, blank_removed = remove_blank_lines(text)
    removed_count += blank_removed

    return text.strip(), removed_count, fixed_spaces


def clean_generic_content(original_content: str) -> Tuple[str, int, int]:
    """
    非 Python 文件：
    - 清理不可见空格
    - 去掉空行
    - 不做激进的注释删除，避免误伤
    """
    text, fixed_spaces = remove_invisible_spaces(original_content)
    text, blank_removed = remove_blank_lines(text)
    return text.strip(), blank_removed, fixed_spaces


def clean_content(original_content: str, lang: str) -> Tuple[str, int, int]:
    if lang == "python":
        return clean_python_content(original_content)
    return clean_generic_content(original_content)


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(2048)
            return b"\x00" in chunk
    except Exception:
        return True


def detect_lang(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext == "py":
        return "python"
    if ext in ("yml", "yaml"):
        return "yaml"
    if ext == "md":
        return "markdown"
    if ext in ("txt", "") or path.name == "requirements.txt":
        return "text"
    if ext in ("json", "html", "xml", "sh", "bash", "ini", "toml", "cfg", "css", "js", "ts"):
        return ext
    return "text"


def normalize_list(items: List[str]) -> List[str]:
    out: List[str] = []
    for it in items:
        if not it:
            continue
        parts = [p.strip() for p in it.split(",") if p.strip()]
        out.extend(parts if parts else [it])
    return out


def should_exclude(
    path: Path,
    project_root: Path,
    exclude_dirs: Set[str],
    exclude_files: Set[str],
    exclude_suffixes: Set[str],
    hard_exclude_dirs: Set[str],
    hard_exclude_files: Set[str],
    hard_exclude_suffixes: Set[str],
) -> bool:
    rel = path.relative_to(project_root)
    parts = [p.lower() for p in rel.parts]
    name = path.name.lower()
    suffix = path.suffix.lower()

    for p in parts[:-1]:
        if p in hard_exclude_dirs or p in exclude_dirs:
            return True

    if name in hard_exclude_files or name in exclude_files:
        return True

    if suffix in hard_exclude_suffixes or suffix in exclude_suffixes:
        return True

    return False


def main():
    parser = argparse.ArgumentParser(
        description="创建项目代码快照。移除 Python 注释、docstring、print 和空行。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--fix-project", action="store_true", help="将清理结果写回磁盘")
    parser.add_argument("--root", default=None, help="项目根目录")
    parser.add_argument("--output", default="PROJECT_SNAPSHOT.md", help="输出文件")
    parser.add_argument("--exclude-dirs", nargs="*", default=[], help="排除目录")
    parser.add_argument("--exclude-files", nargs="*", default=[], help="排除文件")
    parser.add_argument("--exclude-suffixes", nargs="*", default=[], help="排除后缀")
    args = parser.parse_args()

    project_root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    output_file = Path(args.output).resolve() if os.path.isabs(args.output) else project_root / args.output

    max_file_size_bytes = 10 * 1024 * 1024

    hard_exclude_dirs = {
        "__pycache__", ".git", ".idea", ".vscode", "logs", "venv", ".venv", "env",
        ".mypy_cache", ".pytest_cache", "node_modules", "dist", "build",
        "docs", "site-packages", "assets",
        "gpt-related-ci", "gpt-related-scheme",
        "sherpa-onnx-streaming-zipformer-en-20m-2023-02-17",
        "sherpa-onnx-streaming-zipformer-zh-14m",
    }

    hard_exclude_files = {
        "project_snapshot.md", ".ds_store", "create_snapshot.py", "clean_code.py"
    }

    hard_exclude_suffixes = {
        ".pyc", ".pkl", ".lock", ".pt", ".safetensors", ".bin", ".onnx",
        ".xlsx", ".wav", ".webm", ".mp3", ".ogg", ".log",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".bmp", ".tif",
        ".zip", ".rar", ".7z", ".gz", ".tar", ".bz2",
        ".pdf", ".doc", ".docx", ".xls", ".ppt", ".pptx",
        ".db", ".sqlite", ".sqlite3", ".exe", ".dll", ".so", ".a", ".lib", ".o",
        ".ttf", ".woff", ".woff2", ".eot", ".dat", ".cache", ".img", ".iso", ".md", ".txt", ".json"
    }

    user_ex_dirs = set(s.lstrip("/").strip().lower() for s in normalize_list(args.exclude_dirs))
    user_ex_files = set(s.strip().lower() for s in normalize_list(args.exclude_files))
    user_ex_sufs = set((s if s.startswith(".") else f".{s}").lower() for s in normalize_list(args.exclude_suffixes))

    if args.fix_project:
        logger.warning("=" * 60)
        logger.warning("警告：--fix-project 模式已开启！")
        logger.warning("这会修改源文件内容，请确保代码已备份或已提交到 Git。")
        logger.warning("=" * 60)
        if input("输入 yes 确认执行: ").strip().lower() != "yes":
            sys.exit(0)

    try:
        logger.info("Scanning: %s", project_root)

        snapshot_chunks: List[str] = []
        snapshot_chunks.append("# 项目快照\n\n自动生成。已移除 Python 注释、docstring、print 和空行。\n\n")

        processed = 0
        fixed_files = 0
        total_removed = 0

        for path in sorted(project_root.rglob("*")):
            if not path.is_file():
                continue

            if should_exclude(
                path, project_root,
                user_ex_dirs, user_ex_files, user_ex_sufs,
                hard_exclude_dirs, hard_exclude_files, hard_exclude_suffixes
            ):
                continue

            rel = path.relative_to(project_root).as_posix()

            try:
                fsize = path.stat().st_size
                if fsize == 0:
                    continue
                if fsize > max_file_size_bytes:
                    snapshot_chunks.append(f"---\n### {rel} (Skipped Large File)\n\n")
                    continue
            except Exception:
                continue

            if is_binary(path):
                snapshot_chunks.append(f"---\n### {rel} (Skipped Binary)\n\n")
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.error("Error reading %s: %s", rel, e)
                continue

            lang = detect_lang(path)
            cleaned, removed, fixed = clean_content(content, lang)

            if not cleaned:
                continue

            snapshot_chunks.append(
                f"---\n### 文件: `{rel}`\n\n```{lang}\n{cleaned}\n```\n\n"
            )

            processed += 1
            total_removed += removed

            if args.fix_project and (removed > 0 or fixed > 0):
                try:
                    path.write_text(cleaned + "\n", encoding="utf-8")
                    fixed_files += 1
                except Exception as e:
                    logger.error("Write back failed %s: %s", rel, e)

        output_file.write_text("".join(snapshot_chunks), encoding="utf-8")

        logger.info("-" * 60)
        logger.info("快照已生成: %s", output_file)
        logger.info("处理文件数: %s", processed)
        logger.info("总清理行数/项数: %s", total_removed)

        if args.fix_project:
            logger.info("已修改源文件数: %s", fixed_files)

    except Exception as e:
        logger.error("Main error: %s", e, exc_info=True)


if __name__ == "__main__":
    main()