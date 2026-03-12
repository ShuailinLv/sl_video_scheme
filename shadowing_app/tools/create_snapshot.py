#!/usr/bin/env python3
# scripts/create_snapshot.py
# 生成项目快照
# 1) Python 文件：移除“行首 # 注释”、移除函数/类下的 """文档字符串"""、清理不可见空格
# 2) 可选 --fix-project 将清理结果写回磁盘
# 3) 自动跳过二进制文件和过大文件

import os
import sys
import argparse
import logging
import ast
from pathlib import Path
from typing import Tuple, List, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("snapshot")

# --------------------------
# 核心清理逻辑 (优化版)
# --------------------------
def clean_content(original_content: str, lang: str) -> Tuple[str, int, int]:
    spaces_fixed_u = original_content.count("\u00a0")
    spaces_fixed_a = original_content.count("\xa0")
    spaces_fixed_total = spaces_fixed_u + spaces_fixed_a

    # 1. 基础空格清理
    cleaned_text = original_content.replace("\u00a0", " ").replace("\xa0", " ")
    
    comments_removed = 0

    # 2. Python 深度清理 (Docstring + #注释)
    if lang == "python":
        try:
            # 尝试解析语法树来精准定位 docstring
            tree = ast.parse(cleaned_text)
            docstring_ranges = []

            # 遍历所有节点，寻找带有 docstring 的节点 (模块, 函数, 类)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                    # 检查 body 的第一个节点是否为字符串表达式
                    if (node.body and isinstance(node.body[0], ast.Expr) and 
                        isinstance(node.body[0].value, (ast.Str, ast.Constant))):
                        
                        # 兼容性检查：Python 3.8+ 使用 Constant，旧版使用 Str
                        doc_node = node.body[0]
                        # 获取 docstring 的值（再次确认是字符串）
                        if isinstance(doc_node.value, ast.Constant) and isinstance(doc_node.value.value, str):
                             docstring_ranges.append((doc_node.lineno, doc_node.end_lineno))
                        elif isinstance(doc_node.value, ast.Str): # Python < 3.8
                             docstring_ranges.append((doc_node.lineno, doc_node.end_lineno))

            # 准备按行过滤
            lines = cleaned_text.splitlines()
            cleaned_lines: List[str] = []
            
            # 遍历每一行 (注意：ast 行号从 1 开始)
            for i, line in enumerate(lines, start=1):
                # 检查是否在 Docstring 范围内
                is_in_docstring = False
                for start, end in docstring_ranges:
                    if start <= i <= end:
                        is_in_docstring = True
                        break
                
                if is_in_docstring:
                    comments_removed += 1
                    continue

                # 检查是否是 # 注释
                if line.strip().startswith("#"):
                    comments_removed += 1
                    continue

                cleaned_lines.append(line)
            
            cleaned_text = "\n".join(cleaned_lines)

        except SyntaxError:
            # 如果代码本身有语法错误导致无法解析 AST，降级为仅移除 # 注释
            # 避免脚本因为被扫描文件有错而中断
            logger.warning("解析 Python 语法树失败（可能文件包含语法错误），仅执行基础注释清理。")
            lines = cleaned_text.splitlines()
            cleaned_lines = []
            for line in lines:
                if not line.strip().startswith("#"):
                    cleaned_lines.append(line)
                else:
                    comments_removed += 1
            cleaned_text = "\n".join(cleaned_lines)

    return cleaned_text, comments_removed, spaces_fixed_total


# --------------------------
# 工具函数
# --------------------------
def is_binary(path: Path) -> bool:
    """通过检查前 2KB 是否包含 NUL 字节来判断是否为二进制文件"""
    try:
        with path.open("rb") as f:
            chunk = f.read(2048)
            if b'\x00' in chunk:
                return True
    except Exception:
        return True
    return False

def detect_lang(path: Path) -> str:
    """用于 Markdown 代码块语言标记"""
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

def should_exclude(path: Path,
                   project_root: Path,
                   exclude_dirs: Set[str],
                   exclude_files: Set[str],
                   exclude_suffixes: Set[str],
                   hard_exclude_dirs: Set[str],
                   hard_exclude_files: Set[str],
                   hard_exclude_suffixes: Set[str]) -> bool:
    rel = path.relative_to(project_root)
    parts = [p.lower() for p in rel.parts]
    name = path.name.lower()
    suffix = path.suffix.lower()

    # 目录排除
    for p in parts[:-1]:
        if p in hard_exclude_dirs or p in exclude_dirs:
            return True
    # 文件名排除
    if name in hard_exclude_files or name in exclude_files:
        return True
    # 后缀排除
    if suffix in hard_exclude_suffixes or suffix in exclude_suffixes:
        return True

    return False


# --------------------------
# 主流程
# --------------------------
def main():
    parser = argparse.ArgumentParser(
        description="创建项目代码快照。自动移除 Python 的 #注释 和 \"\"\"文档字符串\"\"\"。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--fix-project", action="store_true",
        help="危险：将清理结果写回磁盘（这会永久删除源代码中的 Docstring 和注释！）"
    )
    parser.add_argument("--root", default=None, help="项目根目录")
    parser.add_argument("--output", default="PROJECT_SNAPSHOT.md", help="输出文件")
    parser.add_argument("--exclude-dirs", nargs="*", default=[], help="排除目录")
    parser.add_argument("--exclude-files", nargs="*", default=[], help="排除文件")
    parser.add_argument("--exclude-suffixes", nargs="*", default=[], help="排除后缀")

    args = parser.parse_args()

    project_root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    output_file = (Path(args.output).resolve() if os.path.isabs(args.output) else project_root / args.output)

    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

    # 硬排除规则
    hard_exclude_dirs = {
        "__pycache__", ".git", ".idea", ".vscode", "logs", "venv", ".venv", "env", 
        ".mypy_cache", ".pytest_cache", "node_modules", "dist", "build", ".ds_store", 
        "gpt-related-ci", "gpt-related-scheme", "docs", "site-packages"
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
        ".ttf", ".woff", ".woff2", ".eot", ".dat", ".cache", ".img", ".iso", ".md"
    }

    user_ex_dirs = set(s.lstrip("/").strip().lower() for s in normalize_list(args.exclude_dirs))
    user_ex_files = set(s.strip().lower() for s in normalize_list(args.exclude_files))
    user_ex_sufs = set((s if s.startswith(".") else f".{s}").lower() for s in normalize_list(args.exclude_suffixes))

    if args.fix_project:
        logger.warning("=" * 60)
        logger.warning("警告：--fix-project 模式已开启！")
        logger.warning("这将会从您的源文件中 **永久删除** 所有 #注释 和 \"\"\"文档字符串\"\"\"。")
        logger.warning("请确保已备份代码或在 Git 版本控制下。")
        logger.warning("=" * 60)
        if input("输入 yes 确认执行: ").strip().lower() != "yes":
            sys.exit(0)

    try:
        logger.info(f"Scanning: {project_root}")
        
        snapshot_chunks: List[str] = []
        snapshot_chunks.append("# 项目快照\n\n自动生成的项目代码快照。已移除 Python 注释与文档字符串。\n\n")

        processed = 0
        fixed_files = 0
        total_removed = 0
        
        all_paths = sorted(project_root.rglob("*"))
        
        for path in all_paths:
            if not path.is_file():
                continue
            
            if should_exclude(path, project_root, user_ex_dirs, user_ex_files, user_ex_sufs,
                              hard_exclude_dirs, hard_exclude_files, hard_exclude_suffixes):
                continue

            rel = path.relative_to(project_root).as_posix()
            
            # 检查大小
            try:
                fsize = path.stat().st_size
                if fsize == 0: continue
                if fsize > MAX_FILE_SIZE_BYTES:
                    snapshot_chunks.append(f"---\n### {rel} (Skipped Large File)\n\n")
                    continue
            except: continue

            # 检查二进制
            if is_binary(path):
                snapshot_chunks.append(f"---\n### {rel} (Skipped Binary)\n\n")
                continue

            # 处理内容
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.error(f"Error reading {rel}: {e}")
                continue

            lang = detect_lang(path)
            cleaned, removed, fixed = clean_content(content, lang)

            snapshot_chunks.append(f"---\n### 文件: `{rel}`\n\n```{lang}\n{cleaned.strip()}\n```\n\n")
            processed += 1

            # 写回磁盘逻辑
            if args.fix_project and (removed > 0 or fixed > 0):
                try:
                    path.write_text(cleaned, encoding="utf-8")
                    fixed_files += 1
                    total_removed += removed
                except Exception as e:
                    logger.error(f"Write back failed {rel}: {e}")

        output_file.write_text("".join(snapshot_chunks), encoding="utf-8")
        logger.info("-" * 60)
        logger.info(f"快照已生成: {output_file}")
        logger.info(f"处理文件数: {processed}")
        if args.fix_project:
            logger.info(f"已修改源文件数: {fixed_files} (共移除注释/Docstring行: {total_removed})")

    except Exception as e:
        logger.error(f"Main error: {e}", exc_info=True)

if __name__ == "__main__":
    main()