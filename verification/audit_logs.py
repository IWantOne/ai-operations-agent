"""框架自检：日志登记、写入入口和未使用导入。

用法：在项目根目录运行 `python verification/audit_logs.py`（PYTHONPATH=backend）。
只做静态检查，不写数据库、不启动服务。
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "agent_platform"
sys.path.insert(0, str(ROOT / "backend"))

from agent_platform.logs import catalog

problems = []
for path in sorted(BACKEND.rglob("*.py")):
    if path.name == "__init__.py":
        continue
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if name == "*":
                    continue
                others = [line for index, line in enumerate(lines, 1)
                          if index != node.lineno and re.search(rf"\b{re.escape(name)}\b", line)]
                if not others:
                    problems.append(f"未使用导入 {path.relative_to(ROOT)}:{node.lineno} {name}")

for path in sorted(BACKEND.rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    if path.name != "writer.py" and "store.log(" in text:
        problems.append(f"绕过 LogWriter 写日志：{path.relative_to(ROOT)}")
    for action in re.findall(r'\.write\(\s*"([^"]+)"', text):
        if not any(action == name for (_, name) in catalog.EVENTS):
            problems.append(f"未登记动作 {action} in {path.relative_to(ROOT)}")

corpus = "\n".join(p.read_text(encoding="utf-8") for p in BACKEND.rglob("*.py") if p.name != "catalog.py")
for (table, action) in catalog.EVENTS:
    if action not in corpus:
        problems.append(f"只登记未写入 {table}/{action}")

print(f"日志事件 {len(catalog.EVENTS)} 条，问题 {len(problems)} 个")
for item in problems:
    print(" -", item)
sys.exit(1 if problems else 0)
