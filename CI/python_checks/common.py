from __future__ import annotations

import getpass
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[2]
TARGET_DIRS = [
    ROOT_DIR / "wjx",
    ROOT_DIR / "software",
    ROOT_DIR / "tencent",
    ROOT_DIR / "credamo",
]
ENTRY_FILES = [ROOT_DIR / "SurveyController.py"]
DEPENDENCY_IMPORT_MODULES = ("surveycore",)


CHILD_RESULT_PREFIX = "__WJX_CHECK__"
IMPORT_TIMEOUT_SECONDS = 12
WINDOW_SMOKE_TIMEOUT_SECONDS = 25
UNIT_TEST_TIMEOUT_SECONDS = int(
    os.environ.get("SURVEY_CONTROLLER_UNIT_TEST_TIMEOUT_SECONDS", "120")
)
DEFAULT_UNIT_TEST_COVERAGE_FAIL_UNDER = "70"
PACKAGE_COVERAGE_THRESHOLDS = {
    "software/core": 80.0,
    "software/application": 80.0,
    "software/network": 75.0,
    "providers": 60.0,
    "software/ui": 65.0,
}
TY_TIMEOUT_SECONDS = int(os.environ.get("SURVEY_CONTROLLER_TY_TIMEOUT_SECONDS", "90"))
PYTEST_FAILURE_LOG_TAIL_LINES = 40
TYPE_IGNORE_PATTERNS = (
    re.compile(r"\btype\s*:\s*ignore\b", re.IGNORECASE),
    re.compile(r"\b(?:pyright|basedpyright)\s*:", re.IGNORECASE),
    re.compile(r"\bty\s*:\s*ignore\b", re.IGNORECASE),
)
TYPE_IGNORE_SCAN_ROOTS = (
    ROOT_DIR / "wjx",
    ROOT_DIR / "software",
    ROOT_DIR / "tencent",
    ROOT_DIR / "credamo",
    ROOT_DIR / "CI",
)
TYPE_IGNORE_SCAN_FILES = tuple(ENTRY_FILES)
UNICODE_ESCAPE_PATTERNS = (
    "\\" + "u",
    "\\" + "U",
    "\\" + "N{",
)
UNICODE_ESCAPE_SCAN_ROOTS = (ROOT_DIR / "CI",)
UNICODE_SPACE_TRANSLATION = str.maketrans(
    {
        chr(0x00A0): " ",
        chr(0x2000): " ",
        chr(0x2001): " ",
        chr(0x2002): " ",
        chr(0x2003): " ",
        chr(0x2004): " ",
        chr(0x2005): " ",
        chr(0x2006): " ",
        chr(0x2007): " ",
        chr(0x2008): " ",
        chr(0x2009): " ",
        chr(0x200A): " ",
        chr(0x202F): " ",
        chr(0x205F): " ",
        chr(0x3000): " ",
    }
)

IMPORT_SMOKE_CODE = r"""
import importlib
import json
import os
import sys
import traceback

PREFIX = "__WJX_CHECK__"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WJX_IMPORT_CHECK", "1")

module_name = sys.argv[1]

try:
    importlib.import_module(module_name)
    if module_name == "surveycore":
        from importlib.resources import files

        area_codes = files("surveycore").joinpath("data", "area_codes_2022.json")
        data = json.loads(area_codes.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("provinces"):
            raise ValueError("surveycore 行政区数据缺失或格式错误")
except BaseException as exc:
    payload = {
        "ok": False,
        "kind": "module_import",
        "module": module_name,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }
    print(PREFIX + json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)

print(PREFIX + json.dumps({"ok": True, "kind": "module_import", "module": module_name}, ensure_ascii=False))
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

WINDOW_SMOKE_CODE = r"""
import json
import os
import sys
import traceback

PREFIX = "__WJX_CHECK__"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WJX_IMPORT_CHECK", "1")

try:
    from PySide6.QtWidgets import QApplication

    from software.ui.shell.main_window import create_window

    app = QApplication.instance() or QApplication([])
    create_window()
except BaseException as exc:
    payload = {
        "ok": False,
        "kind": "window_smoke",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }
    print(PREFIX + json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)

print(PREFIX + json.dumps({"ok": True, "kind": "window_smoke"}, ensure_ascii=False))
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""


def configure_console_encoding() -> None:

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def iter_target_dirs() -> list[Path]:
    return [path for path in TARGET_DIRS if path.exists()]


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for target_dir in iter_target_dirs():
        files.extend(path for path in target_dir.rglob("*.py") if "__pycache__" not in path.parts)
    return sorted(set(files))


def iter_compile_targets() -> list[Path]:
    files = iter_python_files()
    for entry_file in ENTRY_FILES:
        if entry_file.exists():
            files.append(entry_file)
    return sorted(files)


def iter_module_names(files: Iterable[Path]) -> list[str]:
    modules: list[str] = list(DEPENDENCY_IMPORT_MODULES)
    for path in files:
        rel = path.relative_to(ROOT_DIR).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        module_name = ".".join(parts)
        if module_name:
            modules.append(module_name)
    return sorted(set(modules), key=lambda name: (name.count("."), name))


def ensure_target_dirs() -> list[Path]:
    target_dirs = iter_target_dirs()
    if not target_dirs:
        print(
            "[ERROR] No scan targets found. Expected at least one of wjx/, software/, or tencent/."
        )
        raise SystemExit(2)
    return target_dirs


def make_child_env() -> dict[str, str]:
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    root_path = str(ROOT_DIR)
    env["PYTHONPATH"] = (
        root_path if not current_python_path else os.pathsep.join([root_path, current_python_path])
    )
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("WJX_IMPORT_CHECK", "1")

    home_dir = (
        env.get("HOME")
        or env.get("USERPROFILE")
        or (
            f"{env.get('HOMEDRIVE', '')}{env.get('HOMEPATH', '')}"
            if env.get("HOMEDRIVE") and env.get("HOMEPATH")
            else ""
        )
    )
    if not home_dir:
        username = getpass.getuser().strip()
        if username:
            guessed_home = Path(env.get("SystemDrive", "C:")) / "Users" / username
            if guessed_home.exists():
                home_dir = str(guessed_home)
    if home_dir:
        env.setdefault("HOME", home_dir)
        env.setdefault("USERPROFILE", home_dir)

    return env


def make_window_smoke_env() -> dict[str, str]:

    env = make_child_env()
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def format_path(path_str: str | Path) -> Path:
    path = Path(path_str)
    try:
        return path.relative_to(ROOT_DIR)
    except ValueError:
        return path


def extract_child_payload(stdout: str, stderr: str) -> dict | None:
    lines = stdout.splitlines() + stderr.splitlines()
    for line in reversed(lines):
        if line.startswith(CHILD_RESULT_PREFIX):
            payload_raw = line[len(CHILD_RESULT_PREFIX) :]
            try:
                return json.loads(payload_raw)
            except json.JSONDecodeError:
                return {"ok": False, "message": payload_raw}
    return None


def summarize_child_output(stdout: str, stderr: str) -> str:
    chunks: list[str] = []
    stdout_text = stdout.strip()
    stderr_text = stderr.strip()
    if stdout_text:
        chunks.append(f"stdout: {stdout_text.splitlines()[-1]}")
    if stderr_text:
        chunks.append(f"stderr: {stderr_text.splitlines()[-1]}")
    return " | ".join(chunks)


def normalize_diagnostic_message(message: str) -> str:

    normalized = message.translate(UNICODE_SPACE_TRANSLATION)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def is_ci_environment() -> bool:
    return os.environ.get("CI", "").strip().lower() == "true" or bool(
        os.environ.get("GITHUB_ACTIONS")
    )


def build_pytest_args(test_target: str, *, verbose_in_ci: bool) -> list[str]:
    args = [sys.executable, "-m", "pytest", test_target]
    if verbose_in_ci and is_ci_environment():
        args.extend(
            [
                "-ra",
                "-vv",
                "--tb=short",
                "--durations=10",
                "--color=yes",
            ]
        )
    else:
        args.append("-q")
    return args


def build_unit_test_pytest_args(*, verbose_in_ci: bool) -> list[str]:
    args = build_pytest_args("CI/unit_tests", verbose_in_ci=verbose_in_ci)
    args.extend(
        [
            "--cov=software",
            "--cov=wjx",
            "--cov=tencent",
            "--cov=credamo",
            "--cov-branch",
            f"--cov-fail-under={DEFAULT_UNIT_TEST_COVERAGE_FAIL_UNDER}",
            "--cov-report=term-missing:skip-covered",
            "--cov-report=xml:coverage.xml",
            "--cov-report=json:coverage.json",
        ]
    )
    return args


def run_compile_checks(files: Iterable[Path]) -> list[dict]:
    issues: list[dict] = []
    for path in files:
        try:
            source = path.read_bytes()
            compile(source, str(path), "exec")
        except (SyntaxError, ValueError, TypeError, OSError) as exc:
            issues.append(
                {
                    "phase": "compile",
                    "path": format_path(path),
                    "message": str(exc).strip(),
                }
            )
    return issues


def run_ruff_check(target_dirs: Iterable[Path]) -> tuple[list[dict], str | None]:
    target_args = [str(path) for path in target_dirs]
    target_args.extend(str(path) for path in ENTRY_FILES if path.exists())
    if not target_args:
        return [], "No target directories found for Ruff checks."

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F",
            *target_args,
            "--output-format",
            "json",
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode == 2:
        message = result.stderr.strip() or result.stdout.strip() or "Ruff execution failed."
        return [], message

    raw = result.stdout.strip()
    try:
        diagnostics: list[dict] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return [], f"Failed to parse Ruff output: {raw}"

    issues: list[dict] = []
    for item in diagnostics:
        issues.append(
            {
                "phase": "ruff",
                "path": format_path(item["filename"]),
                "row": item["location"]["row"],
                "column": item["location"]["column"],
                "code": item.get("code", "?"),
                "message": item.get("message", ""),
            }
        )
    return issues, None


def run_ruff_format_check(target_dirs: Iterable[Path]) -> tuple[list[dict], str | None]:
    target_args = [str(path) for path in target_dirs]
    target_args.extend(str(path) for path in ENTRY_FILES if path.exists())
    if not target_args:
        return [], "No target paths found for Ruff format checks."

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", *target_args],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return [], None
    if result.returncode != 1:
        message = result.stderr.strip() or result.stdout.strip() or "Ruff format execution failed."
        return [], message

    issues: list[dict] = []
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Would reformat:"):
            path = stripped.partition(":")[2].strip()
        elif stripped.startswith("Would reformat "):
            path = stripped.removeprefix("Would reformat ").strip()
        else:
            continue
        issues.append(
            {
                "phase": "ruff-format",
                "path": format_path(path),
                "message": "文件未符合 Ruff 格式；请运行 `uv run ruff format <文件>`。",
            }
        )
    if not issues:
        message = result.stderr.strip() or result.stdout.strip() or "Ruff format check failed."
        return [], message
    return issues, None


def run_ty_check(target_dirs: Iterable[Path]) -> tuple[list[dict], str | None]:
    target_args = [str(path) for path in target_dirs]
    env = make_child_env()
    for entry_file in ENTRY_FILES:
        if entry_file.exists():
            target_args.append(str(entry_file))

    if not target_args:
        return [], "No target paths found for ty diagnostics."

    ty_command = shutil.which("ty")
    if not ty_command:
        return [], "ty is not installed or not available on PATH."

    try:
        result = subprocess.run(
            [
                ty_command,
                "check",
                "--output-format",
                "gitlab",
                "--python",
                sys.executable,
                *target_args,
            ],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=TY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [], f"ty timed out (>{TY_TIMEOUT_SECONDS}s)."

    stderr_text = (result.stderr or "").strip()
    raw = (result.stdout or "").strip()
    if not raw:
        if result.returncode == 0:
            return [], None
        message = stderr_text or "ty failed without producing parseable output."
        return [], message

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [], f"Failed to parse ty output: {raw}"

    if not isinstance(payload, list):
        return [], f"Unexpected ty output format: {raw}"
    issues: list[dict] = []
    for item in payload:
        location = item.get("location", {})
        file_name = location.get("path", "")
        position = location.get("positions", {}).get("begin", {})
        line = position.get("line", 1)
        severity = item.get("severity", "error")
        rule = item.get("check_name") or "ty"
        issues.append(
            {
                "phase": "ty",
                "path": format_path(file_name) if file_name else Path("<unknown>"),
                "row": int(line),
                "column": int(position.get("column", 1)),
                "severity": severity,
                "code": rule,
                "message": normalize_diagnostic_message(item.get("description", "")),
            }
        )

    if result.returncode not in (0, 1):
        message = stderr_text or f"ty exited with status {result.returncode}."
        return [], message

    return issues, None


def run_type_ignore_check(target_dirs: Iterable[Path]) -> list[dict]:

    allowed_roots = {path.resolve() for path in TYPE_IGNORE_SCAN_ROOTS if path.exists()}
    allowed_files = {path.resolve() for path in TYPE_IGNORE_SCAN_FILES if path.exists()}
    issues: list[dict] = []
    for target_dir in target_dirs:
        try:
            resolved_target = target_dir.resolve()
        except OSError:
            continue
        if resolved_target in allowed_files:
            paths = [target_dir]
        elif resolved_target in allowed_roots:
            paths = sorted(
                path for suffix in (".py", ".pyi") for path in target_dir.rglob(f"*{suffix}")
            )
        else:
            continue
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                source = path.read_text(encoding="utf-8", errors="replace")
            try:
                comment_tokens = [
                    token
                    for token in tokenize.generate_tokens(io.StringIO(source).readline)
                    if token.type == tokenize.COMMENT
                ]
            except (IndentationError, tokenize.TokenError):
                continue
            for token in comment_tokens:
                match = None
                for pattern in TYPE_IGNORE_PATTERNS:
                    match = pattern.search(token.string)
                    if match:
                        break
                if match is None:
                    continue
                issues.append(
                    {
                        "phase": "type-ignore",
                        "path": format_path(path),
                        "row": token.start[0],
                        "column": token.start[1] + match.start() + 1,
                        "message": "禁止类型忽略注释和类型检查器指令；请补全类型、收窄类型或使用明确的类型转换。",
                    }
                )
    return issues


def run_unicode_escape_check(target_dirs: Iterable[Path]) -> list[dict]:

    allowed_roots = {path.resolve() for path in UNICODE_ESCAPE_SCAN_ROOTS if path.exists()}
    issues: list[dict] = []
    for target_dir in target_dirs:
        try:
            resolved_target = target_dir.resolve()
        except OSError:
            continue
        if resolved_target not in allowed_roots:
            continue
        for path in sorted(target_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for row, line in enumerate(lines, start=1):
                for pattern in UNICODE_ESCAPE_PATTERNS:
                    column = line.find(pattern)
                    if column < 0:
                        continue
                    issues.append(
                        {
                            "phase": "unicode-escape",
                            "path": format_path(path),
                            "row": row,
                            "column": column + 1,
                            "message": "CI 代码禁止 Unicode 转义序列，请直接写字符，或用 chr(0xXXXX) 这类形式表达。",
                        }
                    )
    return issues


def run_module_import_checks(modules: Iterable[str]) -> list[dict]:
    issues_by_signature: dict[tuple[str, str, str], dict] = {}
    env = make_child_env()

    for module_name in modules:
        try:
            result = subprocess.run(
                [sys.executable, "-c", IMPORT_SMOKE_CODE, module_name],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                env=env,
                timeout=IMPORT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            signature = ("TimeoutError", f"Import timed out (>{IMPORT_TIMEOUT_SECONDS}s).", "")
            issue = issues_by_signature.setdefault(
                signature,
                {
                    "phase": "import",
                    "modules": [],
                    "message": signature[1],
                    "error_type": signature[0],
                    "traceback": signature[2],
                },
            )
            issue["modules"].append(module_name)
            continue

        payload = extract_child_payload(result.stdout, result.stderr) or {}
        if result.returncode == 0 and payload.get("ok"):
            continue

        error_type = payload.get("error_type", "ImportError")
        fallback_message = summarize_child_output(result.stdout, result.stderr)
        message = payload.get("message") or fallback_message or "Module import failed."
        traceback_text = payload.get("traceback", "").strip()
        signature = (error_type, message, traceback_text)
        issue = issues_by_signature.setdefault(
            signature,
            {
                "phase": "import",
                "modules": [],
                "message": message,
                "error_type": error_type,
                "traceback": traceback_text,
            },
        )
        issue["modules"].append(module_name)

    return list(issues_by_signature.values())


def run_window_smoke_check() -> dict | None:
    env = make_window_smoke_env()
    try:
        result = subprocess.run(
            [sys.executable, "-c", WINDOW_SMOKE_CODE],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            env=env,
            timeout=WINDOW_SMOKE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "phase": "window",
            "message": f"Main window creation timed out (>{WINDOW_SMOKE_TIMEOUT_SECONDS}s).",
        }

    payload = extract_child_payload(result.stdout, result.stderr) or {}
    if payload.get("kind") == "window_smoke" and payload.get("ok") is True:
        return None

    fallback_message = summarize_child_output(result.stdout, result.stderr)
    return {
        "phase": "window",
        "message": payload.get("message") or fallback_message or "Main window creation failed.",
        "error_type": payload.get("error_type", "RuntimeError"),
        "traceback": payload.get("traceback", "").strip(),
    }


def extract_coverage_summary(stdout: str) -> str | None:
    lines = stdout.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip().startswith("Name") and "Cover" in line:
            start_index = index
            break

    if start_index is None:
        return None

    summary_lines: list[str] = []
    for line in lines[start_index:]:
        stripped = line.rstrip()
        if not stripped:
            if summary_lines:
                break
            continue
        summary_lines.append(stripped)
        if stripped.startswith("TOTAL"):
            break

    return "\n".join(summary_lines) if summary_lines else None


def check_package_coverage(payload: dict) -> list[dict]:
    files = payload.get("files")
    if not isinstance(files, dict):
        return [{"phase": "unit", "message": "Coverage JSON does not contain a files object."}]

    diagnostics: list[dict] = []
    for package, threshold in PACKAGE_COVERAGE_THRESHOLDS.items():
        matching = [
            data.get("summary", {})
            for file_name, data in files.items()
            if file_name.replace("\\", "/").startswith(package)
        ]
        if package == "providers":
            matching = [
                data.get("summary", {})
                for file_name, data in files.items()
                if file_name.replace("\\", "/").startswith(
                    ("software/providers/", "wjx/", "tencent/", "credamo/")
                )
            ]
        statements = sum(int(item.get("num_statements", 0)) for item in matching)
        covered = sum(int(item.get("covered_lines", 0)) for item in matching)
        if statements <= 0:
            diagnostics.append(
                {
                    "phase": "unit",
                    "message": f"Coverage data is missing for {package}.",
                }
            )
            continue
        percent = covered / statements * 100
        if percent < threshold:
            diagnostics.append(
                {
                    "phase": "unit",
                    "message": (
                        f"{package} coverage is {percent:.1f}%; "
                        f"the required minimum is {threshold:.0f}%."
                    ),
                }
            )
    return diagnostics


def run_unit_tests() -> tuple[dict | None, str | None]:
    env = make_child_env()
    try:
        result = subprocess.run(
            build_unit_test_pytest_args(verbose_in_ci=True),
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=UNIT_TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_text = (exc.stdout or "").strip()
        stderr_text = (exc.stderr or "").strip()
        return {
            "phase": "unit",
            "message": f"Unit tests timed out (>{UNIT_TEST_TIMEOUT_SECONDS}s).",
            "stdout": stdout_text,
            "stderr": stderr_text,
        }, None

    coverage_summary = extract_coverage_summary(result.stdout or "")

    coverage_issues: list[dict] = []
    if result.returncode == 0:
        try:
            coverage_payload = json.loads((ROOT_DIR / "coverage.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            coverage_issues = [{"phase": "unit", "message": f"读取覆盖率 JSON 失败：{exc}"}]
        else:
            coverage_issues = check_package_coverage(coverage_payload)

    if result.returncode == 0 and not coverage_issues:
        return None, coverage_summary

    summary = summarize_child_output(result.stdout, result.stderr) or "Unit tests failed."
    if coverage_issues:
        summary = "\n".join([summary, *(item["message"] for item in coverage_issues)])
    return {
        "phase": "unit",
        "message": summary,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }, coverage_summary


def print_issues(title: str, issues: Iterable[dict]) -> None:
    issue_list = list(issues)
    if not issue_list:
        return

    print(title)
    for index, item in enumerate(issue_list, start=1):
        phase = item["phase"]
        if phase == "ruff":
            print(
                f"{index}. {item['path']}:{item['row']}:{item['column']}  [{item.get('code', '?')}]"
            )
            print(f"   {item['message']}")
            continue

        if phase == "compile":
            print(f"{index}. {item['path']}")
            print(f"   {item['message']}")
            continue

        if phase == "import":
            error_type = item.get("error_type", "ImportError")
            modules_text = ", ".join(item.get("modules", []))
            print(f"{index}. {modules_text}  [{error_type}]")
            print(f"   {item['message']}")
            traceback_text = item.get("traceback")
            if traceback_text:
                print("   Import traceback:")
                for line in traceback_text.splitlines():
                    print(f"   {line}")
            continue

        if phase == "window":
            error_type = item.get("error_type", "RuntimeError")
            print(f"{index}. Main window creation  [{error_type}]")
            print(f"   {item['message']}")
            traceback_text = item.get("traceback")
            if traceback_text:
                print("   Runtime traceback:")
                for line in traceback_text.splitlines():
                    print(f"   {line}")
            continue

        if phase == "unit":
            print(f"{index}. Unit tests")
            print(f"   {item['message']}")
            stdout_text = item.get("stdout")
            stderr_text = item.get("stderr")
            if stdout_text:
                print("   pytest stdout:")
                for line in stdout_text.splitlines()[-PYTEST_FAILURE_LOG_TAIL_LINES:]:
                    print(f"   {line}")
            if stderr_text:
                print("   pytest stderr:")
                for line in stderr_text.splitlines()[-PYTEST_FAILURE_LOG_TAIL_LINES:]:
                    print(f"   {line}")
            continue

        if phase == "ty":
            print(
                f"{index}. {item['path']}:{item['row']}:{item['column']}  "
                f"[{item.get('severity', 'error')}/{item.get('code', 'ty')}]"
            )
            message_lines = str(item.get("message", "")).splitlines() or [""]
            print(f"   {message_lines[0]}")
            for line in message_lines[1:]:
                print(f"   {line}")
            continue

        if phase == "ruff-format":
            print(f"{index}. {item['path']}")
            print(f"   {item['message']}")
            continue

        if phase in {"type-ignore", "unicode-escape"}:
            print(f"{index}. {item['path']}:{item['row']}:{item['column']}")
            print(f"   {item['message']}")


def print_scan_targets(target_dirs: Iterable[Path]) -> None:
    print(
        f"[INFO] Scan targets: {', '.join(str(path.relative_to(ROOT_DIR)) for path in target_dirs)}"
    )
