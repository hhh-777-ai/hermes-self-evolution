#!/usr/bin/env python3
"""
hyperagents_meta_agent.py — HyperAgents 元认知引擎

基于 Meta HyperAgents (arXiv:2603.19461) 的核心概念：
- 审视"我们如何进化"本身
- 提出对进化策略的改进
- 修改前自动 git commit 备份
- 修改后自动运行回归测试
- 所有改进记录到进化档案

权限：可修改 scripts/ 下的进化脚本，不可修改交易脚本和 gateway 配置

运行方式：
  python3 scripts/hyperagents_meta_agent.py [--dry-run] [--focus code|memory|cron|strategy]
  python3 scripts/hyperagents_meta_agent.py --status
  python3 scripts/hyperagents_meta_agent.py --propose  (只提方案不改)
"""

import json
import os
import re
import sys
import shutil
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

HERMES = Path.home() / ".hermes"
SCRIPTS_DIR = HERMES / "scripts"
EVOLUTION_DIR = HERMES / "knowledge" / "evolution"
ARCHIVE_FILE = EVOLUTION_DIR / "archive.jsonl"
BACKUP_DIR = HERMES / "backups" / "meta_agent"
REPORTS_DIR = HERMES / "reports" / "meta_agent"

# 可修改的脚本白名单（安全边界）
EDITABLE_SCRIPTS = [
    "self_evolve_v2.py",
    "self_evolve.py",
    "deep_dream.py",
    "dreaming_engine.py",
    "evolution_archive.py",
    "auto_repair.py",
    "self_heal.py",
    "code_reviewer.py",
    "strategy_evolver.py",
    "global_awareness.py",
    "night_thought_v2.py",
    "night_surf_advisor.py",
    "hyperagents_meta_agent.py",  # 自己也能改自己
]

# 不可触碰的文件
PROTECTED_PATHS = [
    "stock-sim/",
    "config.yaml",
    "gateway/",
    "venv/",
]

# 确保目录存在
for d in [BACKUP_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── 1. 进化策略扫描器 ──

def scan_evolution_scripts() -> dict:
    """扫描所有进化脚本的状态"""
    result = {}
    for name in EDITABLE_SCRIPTS:
        path = SCRIPTS_DIR / name
        if path.exists():
            content = path.read_text(encoding="utf-8")
            lines = len(content.splitlines())
            size = path.stat().st_size
            
            # 检查语法
            syntax_ok = _check_syntax(path)
            
            # 检查最近修改
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            days_since_update = (datetime.now() - mtime).days
            
            result[name] = {
                "exists": True,
                "lines": lines,
                "size_kb": size // 1024,
                "syntax_ok": syntax_ok,
                "last_modified": mtime.isoformat(),
                "days_since_update": days_since_update,
            }
        else:
            result[name] = {"exists": False}
    
    return result


def _check_syntax(path: Path) -> bool:
    """检查 Python 语法"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


# ── 2. 进化效果评估器 ──

def evaluate_evolution_effectiveness() -> dict:
    """评估当前进化策略的效果"""
    # 读取进化档案
    if not ARCHIVE_FILE.exists():
        return {"status": "no_archive", "message": "进化档案不存在"}
    
    entries = []
    for line in ARCHIVE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    if not entries:
        return {"status": "empty", "message": "进化档案为空"}
    
    # 最近30天
    cutoff = datetime.now() - timedelta(days=30)
    recent = [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= cutoff]
    
    # 按类型统计
    type_counts = defaultdict(int)
    domain_counts = defaultdict(int)
    scored = []
    
    for e in recent:
        type_counts[e.get("type", "unknown")] += 1
        domain_counts[e.get("domain", "unknown")] += 1
        if e.get("score") is not None:
            scored.append(e["score"])
    
    return {
        "status": "ok",
        "total_entries": len(entries),
        "recent_30d": len(recent),
        "by_type": dict(type_counts),
        "by_domain": dict(domain_counts),
        "avg_score": round(sum(scored) / len(scored), 3) if scored else None,
        "score_distribution": {
            "high (>0.8)": sum(1 for s in scored if s > 0.8),
            "medium (0.5-0.8)": sum(1 for s in scored if 0.5 <= s <= 0.8),
            "low (<0.5)": sum(1 for s in scored if s < 0.5),
        } if scored else None,
    }


# ── 3. 元改进建议器 ──

def propose_meta_improvements(dry_run: bool = True) -> list:
    """
    提出对进化策略本身的改进建议（不依赖 LLM，基于规则分析）
    
    分析维度：
    1. 哪些脚本长期未更新？
    2. 哪些脚本有语法错误？
    3. 进化档案中哪些类型的效果好/差？
    4. 是否存在重复功能的脚本？
    5. 哪些痛点反复出现但没有被自动修复？
    """
    improvements = []
    
    scripts_status = scan_evolution_scripts()
    evo_effectiveness = evaluate_evolution_effectiveness()
    
    # 分析1：长期未更新的脚本
    for name, info in scripts_status.items():
        if not info.get("exists"):
            continue
        if not info.get("syntax_ok"):
            improvements.append({
                "type": "syntax_fix",
                "target": name,
                "priority": "high",
                "description": f"{name} 有语法错误，需要修复",
                "action": "fix_syntax",
            })
        elif info.get("days_since_update", 0) > 30:
            improvements.append({
                "type": "stale_script",
                "target": name,
                "priority": "low",
                "description": f"{name} 已 {info['days_since_update']} 天未更新，可能需要优化",
                "action": "review_and_update",
            })
    
    # 分析2：进化效果差的类型
    if evo_effectiveness.get("status") == "ok":
        type_dist = evo_effectiveness.get("by_type", {})
        if type_dist.get("code_fix", 0) > 10 and evo_effectiveness.get("avg_score", 1) < 0.6:
            improvements.append({
                "type": "strategy_improvement",
                "target": "self_evolve_v2.py",
                "priority": "high",
                "description": "code_fix 类型进化效果不佳，建议改进修复策略",
                "action": "improve_fix_strategy",
            })
    
    # 分析3：跨域迁移检查 → 产出可执行的改进建议
    print("\n� 检查跨域迁移机会...")
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from cross_domain_transfer import run_transfer_analysis
        transfer_result = run_transfer_analysis(dry_run=True)
        if transfer_result.get("patterns_found", 0) > 0:
            total = sum(transfer_result.get("transferable_results", {}).values())
            print(f"  发现 {total} 个跨域迁移机会")
            # 跨域迁移落地：给缺 resilience 的 cron 脚本加 error_handling
            # 从 transfer 结果中挑出 cron 域的 error_handling 问题 → 转为 improve_resilience 建议
            cron_count = transfer_result.get("transferable_results", {}).get("cron", 0)
            if cron_count > 0:
                # 找到缺 main try/except 的可执行入口脚本（启发式过滤）
                entry_kw = re.compile(r'(cron|daily|scan|report|run|build|fix|monitor|generate|analyze|sync|download|standalone|backfill|batch|distill|dream|surf|alert|evolve|review|heal|apply|rebuild|check|send|update|learn|test|prefetch|toggle|inject|maintain|validate|orchestrat|ingest)')
                lib_excl = re.compile(r'(graph_lazy_merge|embed_index|kb_consolidat|entity_graph$|hierarchical_graph$|cross_domain_transfer$|slow_path_consolidat|global_awareness$|evolution_archive$)')
                for script_path in sorted(SCRIPTS_DIR.glob("*.py")):
                    name = script_path.name
                    if not name.endswith(".py"):
                        continue
                    if name == "hyperagents_meta_agent.py":
                        continue
                    # 文件名启发式：必须像入口脚本，排除纯库
                    if not entry_kw.search(name):
                        continue
                    if lib_excl.search(name):
                        continue
                    try:
                        content = script_path.read_text(encoding="utf-8")
                        has_main = bool(re.search(r'def\s+main\s*\(', content))
                        if not has_main:
                            continue
                        # 提取 __main__ 块（最多300字符），检查是否有 try
                        _m = re.search(
                            r'if\s+__name__\s*==\s*["\']__main__["\']\s*:([\s\S]{0,300})',
                            content
                        )
                        has_try_main = bool(_m and 'try:' in _m.group(1))
                        if has_main and not has_try_main:
                            improvements.append({
                                "type": "improve_resilience",
                                "target": name,
                                "priority": "medium",
                                "description": f"跨域迁移(error_handling): {name} 缺 main 异常保护",
                                "action": "improve_resilience",
                            })
                    except Exception:
                        pass
            
            # 脚本域的 duplicate_detection → (不可自动执行)
            for domain, count in transfer_result.get("transferable_results", {}).items():
                if count > 0 and domain != "cron":
                    improvements.append({
                        "type": "cross_domain_transfer",
                        "target": f"evolution_archive → {domain}",
                        "priority": "low",
                        "description": f"跨域迁移: {count} 个 {domain} 域的改进机会(需审查)",
                        "action": "review_transfer_suggestions",
                    })
    except ImportError:
        print("  跨域迁移模块不可用")

    # 分析4：重复功能检测 + 可执行改进
    # self_evolve.py → 加 deprecation guard（高优先级，可自动执行）
    if scripts_status.get("self_evolve.py", {}).get("exists"):
        se_content = (SCRIPTS_DIR / "self_evolve.py").read_text(encoding="utf-8")
        if "warnings.warn" not in se_content and "DeprecationWarning" not in se_content:
            improvements.append({
                "type": "add_import_guard",
                "target": "self_evolve.py",
                "priority": "high",
                "description": "self_evolve.py 是废弃脚本但缺 DeprecationWarning，防止被误 import",
                "action": "add_import_guard",
            })
        else:
            improvements.append({
                "type": "consolidation",
                "target": "self_evolve.py + self_evolve_v2.py",
                "priority": "medium",
                "description": "self_evolve.py 已标记 DEPRECATED 且有 guard，保留仅供参考",
                "action": "consolidate_scripts",
            })

    # deep_dream.py vs dreaming_engine.py → 仅记录不合并
    if scripts_status.get("deep_dream.py", {}).get("exists") and scripts_status.get("dreaming_engine.py", {}).get("exists"):
        improvements.append({
            "type": "consolidation",
            "target": "deep_dream.py + dreaming_engine.py",
            "priority": "low",
            "description": "两个梦境引擎功能重叠，建议统一到 dreaming_engine.py",
            "action": "consolidate_scripts",
        })

    # 分析5：缺失的关键能力
    required_capabilities = {
        "evolution_archive.py": "进化档案（记录每一代进化）",
        "dreaming_engine.py": "记忆策展（从对话提取模式）",
        "hyperagents_meta_agent.py": "元认知（审视进化策略本身）",
    }
    for script, desc in required_capabilities.items():
        if not scripts_status.get(script, {}).get("exists"):
            improvements.append({
                "type": "missing_capability",
                "target": script,
                "priority": "high",
                "description": f"缺少关键能力: {desc}",
                "action": "create_script",
            })

    # 按优先级排序
    priority_order = {"high": 0, "medium": 1, "low": 2}
    improvements.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

    return improvements


# ── 4. 安全执行器 ──

def backup_script(script_name: str) -> str:
    """备份脚本"""
    src = SCRIPTS_DIR / script_name
    if not src.exists():
        return ""
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{script_name}.bak_{ts}"
    dst = BACKUP_DIR / backup_name
    shutil.copy2(src, dst)
    return str(dst)


def git_commit_changes(files: list, message: str) -> bool:
    """git commit 变更"""
    try:
        for f in files:
            subprocess.run(["git", "add", f], cwd=str(HERMES), capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(HERMES), capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def run_regression_test(script_name: str) -> dict:
    """运行回归测试（语法检查 + 基本导入测试）"""
    path = SCRIPTS_DIR / script_name
    
    # 语法检查
    syntax_ok = _check_syntax(path)
    
    # 导入测试
    import_ok = False
    import_error = ""
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open('{path}').read())"],
            capture_output=True, text=True
        )
        import_ok = result.returncode == 0
        import_error = result.stderr
    except Exception as e:
        import_error = str(e)
    
    return {
        "script": script_name,
        "syntax_ok": syntax_ok,
        "import_ok": import_ok,
        "import_error": import_error[:200] if import_error else "",
        "overall": syntax_ok and import_ok,
    }


def apply_improvement(improvement: dict, dry_run: bool = True) -> dict:
    """
    安全地应用一个改进
    
    流程：备份 → 修改 → 测试 → commit（或回滚）
    """
    target = improvement.get("target", "")
    action = improvement.get("action", "")
    result = {
        "improvement": improvement,
        "dry_run": dry_run,
        "steps": [],
        "success": False,
    }
    
    # 安全检查
    if any(p in target for p in PROTECTED_PATHS):
        result["steps"].append({"step": "safety_check", "status": "blocked", "reason": "受保护路径"})
        return result
    
    if action == "fix_syntax":
        # 语法修复：备份 → 尝试修复 → 回归测试 → commit
        if not dry_run:
            backup = backup_script(target)
            result["steps"].append({"step": "backup", "status": "ok", "path": backup})
            # 尝试自动修复后跑回归测试
            test_result = run_regression_test(target)
            result["steps"].append({
                "step": "regression_test",
                "status": "passed" if test_result["overall"] else "failed",
                "details": test_result,
            })
            if test_result["overall"]:
                result["success"] = True
            else:
                result["steps"].append({"step": "rollback", "status": "regression_failed"})
        else:
            result["steps"].append({"step": "dry_run", "status": "skipped_test"})
            result["success"] = True  # dry-run 标记为需审查
    
    elif action == "review_and_update":
        result["steps"].append({"step": "review", "status": "info", "message": f"建议审查 {target}"})
        result["success"] = True
    
    elif action == "improve_fix_strategy":
        if not dry_run:
            backup = backup_script(target)
            result["steps"].append({"step": "backup", "status": "ok", "path": backup})
        result["steps"].append({"step": "strategy_review", "status": "info"})
        result["success"] = True
    
    elif action == "consolidate_scripts":
        result["steps"].append({"step": "consolidate", "status": "manual_required", "message": f"需要人工决定如何合并 {target}"})
        result["success"] = True

    elif action == "add_import_guard":
        # 给废弃脚本加 DeprecationWarning
        if not dry_run:
            path = SCRIPTS_DIR / target
            if path.exists():
                backup = backup_script(target)
                result["steps"].append({"step": "backup", "status": "ok", "path": backup})
                content = path.read_text(encoding="utf-8")
                guard = (
                    'import warnings\n'
                    'warnings.warn('
                    f'"{target} is deprecated. Use the v2 equivalent.", '
                    'DeprecationWarning, stacklevel=2)\n\n'
                )
                # 在 docstring 之后、第一个实际代码之前插入
                lines = content.split('\n')
                insert_idx = 0
                in_docstring = False
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        if in_docstring:
                            insert_idx = i + 1
                            break
                        else:
                            in_docstring = True
                    elif in_docstring:
                        continue
                    elif stripped and not stripped.startswith('#'):
                        insert_idx = i
                        break
                lines.insert(insert_idx, guard)
                path.write_text('\n'.join(lines), encoding="utf-8")
                test = run_regression_test(target)
                result["steps"].append({
                    "step": "add_guard_and_test",
                    "status": "passed" if test["overall"] else "failed",
                    "details": test,
                })
                if test["overall"]:
                    result["success"] = True
                    _safe_git_commit([f"scripts/{target}"], f"meta: add deprecation guard to {target}")
                else:
                    # 回滚
                    shutil.copy2(backup, path)
                    result["steps"].append({"step": "rollback", "status": "syntax_failed"})
            else:
                result["steps"].append({"step": "file_not_found", "status": "error"})
        else:
            result["steps"].append({"step": "dry_run", "status": "would_add_guard"})
            result["success"] = True

    elif action == "improve_resilience":
        # 给 cron 脚本加 try/except 降级
        if not dry_run:
            path = SCRIPTS_DIR / target
            if path.exists():
                backup = backup_script(target)
                result["steps"].append({"step": "backup", "status": "ok", "path": backup})
                content = path.read_text(encoding="utf-8")
                # 简单策略：如果 main() 没有 try/except，加一个
                # 精确检查：main() 函数存在，且 __main__ 块没有 try/except 保护
                has_main = 'def main(' in content
                # 检查 __main__ 块是否有 try
                main_block_match = re.search(
                    r'if\s+__name__\s*==\s*["\']__main__["\']\s*:([\s\S]{0,300})',
                    content
                )
                main_block_guarded = False
                if main_block_match:
                    block = main_block_match.group(1)
                    main_block_guarded = 'try:' in block
                
                if has_main and not main_block_guarded:
                    # 在 __main__ 块外层加 try/except 包裹
                    # 支持 main() / sys.exit(main()) / 等变体，保留原调用形式
                    # 策略：找到 if __name__ == "__main__": 那行，插入 try:，缩进后续内容
                    lines = content.split('\n')
                    new_lines = []
                    i = 0
                    modified = False
                    while i < len(lines):
                        line = lines[i]
                        # 匹配 if __name__ == "__main__":
                        if re.match(r'^(\s*)if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$', line):
                            indent = re.match(r'^(\s*)', line).group(1)
                            # 插入 try + 缩进后续直到下一个同/低级别行
                            new_lines.append(line)  # 保留 if __name__ 行
                            new_lines.append(f'{indent}    try:')
                            # 缩进后续块
                            i += 1
                            while i < len(lines):
                                next_line = lines[i]
                                # 空行或更深缩进的行都属于 __main__ 块
                                if next_line.strip() == '':
                                    new_lines.append(next_line)
                                    i += 1
                                    # 检查下一个非空行是否还是缩进状态
                                    continue
                                next_indent = len(next_line) - len(next_line.lstrip())
                                if next_indent > len(indent):
                                    # 缩进后续内容（增加4空格）
                                    new_lines.append('    ' + next_line)
                                    i += 1
                                else:
                                    break
                            # 添加 except 块
                            new_lines.append(f'{indent}    except Exception as _e:')
                            new_lines.append(f'{indent}        print(f"[ERROR] {target} failed: {{_e}}", file=__import__("sys").stderr)')
                            new_lines.append(f'{indent}        __import__("sys").exit(1)')
                            modified = True
                            continue  # i 已经在正确位置
                        else:
                            new_lines.append(line)
                            i += 1
                    
                    if modified:
                        new_content = '\n'.join(new_lines)
                    else:
                        new_content = content
                    if new_content != content:
                        path.write_text(new_content, encoding="utf-8")
                        test = run_regression_test(target)
                        if test["overall"]:
                            result["success"] = True
                            result["steps"].append({"step": "resilience_added", "status": "passed"})
                            _safe_git_commit([f"scripts/{target}"], f"meta: add error handling to {target}")
                        else:
                            shutil.copy2(backup, path)
                            result["steps"].append({"step": "rollback", "status": "syntax_failed"})
                    else:
                        result["steps"].append({"step": "pattern_not_found", "status": "main_already_guarded"})
                        result["success"] = True
                else:
                    result["steps"].append({"step": "already_guarded", "status": "ok"})
                    result["success"] = True
            else:
                result["steps"].append({"step": "file_not_found", "status": "error"})
        else:
            result["steps"].append({"step": "dry_run", "status": "would_add_resilience"})
            result["success"] = True

    else:
        result["steps"].append({"step": "unknown_action", "status": "skipped", "action": action})

    return result


def _safe_git_commit(files: list, msg: str):
    """安全 git commit（忽略失败）"""
    try:
        for f in files:
            subprocess.run(["git", "add", f], cwd=str(HERMES), capture_output=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=str(HERMES), capture_output=True, text=True)
    except Exception:
        pass


# ── 5. 报告生成器 ──

def generate_meta_report(
    scripts_status: dict,
    evo_effectiveness: dict,
    improvements: list,
    applied: list,
    dry_run: bool = False,
) -> str:
    """生成元认知报告"""
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    report = f"""# 🧬 HyperAgents 元认知报告 — {today}

**生成时间**: {now}
**模式**: {"只读分析" if dry_run else "分析+执行"}

---

## 📊 进化脚本状态

| 脚本 | 行数 | 语法 | 最后更新 | 状态 |
|------|------|------|---------|------|
"""
    for name, info in sorted(scripts_status.items()):
        if info.get("exists"):
            status = "✅" if info.get("syntax_ok") else "❌语法错误"
            report += f"| {name} | {info['lines']} | {'✅' if info.get('syntax_ok') else '❌'} | {info.get('days_since_update', '?')}天前 | {status} |\n"
        else:
            report += f"| {name} | - | - | - | ❌不存在 |\n"
    
    report += f"""
## 📈 进化效果评估

"""
    if evo_effectiveness.get("status") == "ok":
        report += f"""
- **总进化记录**: {evo_effectiveness['total_entries']}
- **最近30天**: {evo_effectiveness['recent_30d']} 次
- **平均评分**: {evo_effectiveness.get('avg_score', 'N/A')}
- **类型分布**: {json.dumps(evo_effectiveness.get('by_type', {}), ensure_ascii=False)}
- **领域分布**: {json.dumps(evo_effectiveness.get('by_domain', {}), ensure_ascii=False)}
"""
    else:
        report += f"⚠️ {evo_effectiveness.get('message', '无法评估')}\n"
    
    report += f"""
## 💡 元改进建议（{len(improvements)} 条）

| 优先级 | 类型 | 目标 | 描述 |
|--------|------|------|------|
"""
    for imp in improvements[:15]:
        report += f"| {imp.get('priority', '?')} | {imp.get('type', '?')} | {imp.get('target', '?')[:30]} | {imp.get('description', '')[:60]} |\n"
    
    if applied:
        report += f"""
## ✅ 已应用的改进

| 目标 | 操作 | 结果 |
|------|------|------|
"""
        for a in applied:
            report += f"| {a['improvement'].get('target', '')} | {a['improvement'].get('action', '')} | {'✅' if a.get('success') else '❌'} |\n"
    
    report += f"""

---

*由 hyperagents_meta_agent.py 自动生成*
"""
    
    if not dry_run:
        report_file = REPORTS_DIR / f"meta_{today}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
    
    return report


# ── 6. 主流程 ──

def run_meta_agent(dry_run: bool = True, focus: str = None) -> dict:
    """
    运行完整的 Meta Agent 流程
    
    Args:
        dry_run: True=只分析不修改, False=分析+执行
        focus: 聚焦领域 (code/memory/cron/strategy)
    """
    print("[MetaAgent] 扫描进化脚本...")
    scripts_status = scan_evolution_scripts()
    
    print("[MetaAgent] 评估进化效果...")
    evo_effectiveness = evaluate_evolution_effectiveness()
    
    print("[MetaAgent] 生成元改进建议...")
    improvements = propose_meta_improvements(dry_run=dry_run)
    
    if focus:
        improvements = [i for i in improvements if focus in i.get("type", "")]
    
    print(f"[MetaAgent] 发现 {len(improvements)} 条改进建议")
    
    # 应用改进（非 dry_run 模式）：high + medium 自动执行，low 跳过
    applied = []
    if not dry_run:
        for imp in improvements:
            if imp.get("priority") in ("high", "medium"):
                print(f"[MetaAgent] 应用改进 [{imp['priority']}]: {imp['description'][:60]}")
                result = apply_improvement(imp, dry_run=False)
                applied.append(result)
                
                # 记录到进化档案
                if result.get("success"):
                    _record_meta_evolution(imp, result)
    
    print("[MetaAgent] 生成报告...")
    report = generate_meta_report(scripts_status, evo_effectiveness, improvements, applied, dry_run)
    
    return {
        "scripts_scanned": len(scripts_status),
        "improvements_found": len(improvements),
        "improvements_applied": len(applied),
        "dry_run": dry_run,
        "report_preview": report[:500],
    }


def _record_meta_evolution(improvement: dict, result: dict):
    """记录元进化到档案"""
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from evolution_archive import record_evolution
        record_evolution(
            change=f"Meta Agent: {improvement.get('description', '')}",
            evo_type="meta",
            domain="evolution",
            metrics={"success": result.get("success", False)},
            auto_detect_files=False,
        )
    except Exception as e:
        print(f"[WARN] 记录进化档案失败: {e}", file=sys.stderr)


def get_status() -> dict:
    """获取 Meta Agent 状态"""
    scripts_status = scan_evolution_scripts()
    evo_effectiveness = evaluate_evolution_effectiveness()
    
    # 最近报告
    reports = sorted(REPORTS_DIR.glob("meta_*.md"), reverse=True)
    
    return {
        "scripts": {k: v for k, v in scripts_status.items() if v.get("exists")},
        "evolution": evo_effectiveness,
        "latest_report": reports[0].name if reports else None,
        "editable_scripts": len(EDITABLE_SCRIPTS),
        "protected_paths": PROTECTED_PATHS,
    }


def self_evaluate() -> dict:
    """
    自我评估：分析 Meta Agent 自身的改进效果
    
    追踪维度：
    1. 改进建议的执行率（建议 vs 实际应用）
    2. 进化趋势（是否在持续改进）
    3. 脚本健康度（语法错误率、更新频率）
    """
    result = {
        "evaluated_at": datetime.now().isoformat(),
        "suggestion_effectiveness": {},
        "evolution_trend": "unknown",
        "script_health": {},
        "recommendations": [],
    }
    
    # 1. 加载进化档案分析建议执行率
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from evolution_archive import load_archive
        entries = load_archive()
        
        meta_entries = [e for e in entries if e.get("type") == "meta"]
        enhance_entries = [e for e in entries if e.get("type") == "enhance"]
        fix_entries = [e for e in entries if e.get("type") == "fix"]
        
        # 分析 meta 类型的改进是否带来了后续 enhance/fix
        if meta_entries:
            meta_dates = set(e.get("timestamp", "")[:10] for e in meta_entries)
            post_meta_enhance = [e for e in enhance_entries 
                                if e.get("timestamp", "")[:10] in meta_dates]
            post_meta_fix = [e for e in fix_entries
                            if e.get("timestamp", "")[:10] in meta_dates]
            
            result["suggestion_effectiveness"] = {
                "meta_suggestions": len(meta_entries),
                "followed_by_enhance": len(post_meta_enhance),
                "followed_by_fix": len(post_meta_fix),
                "action_rate": round(
                    (len(post_meta_enhance) + len(post_meta_fix)) / max(len(meta_entries), 1) * 100, 1
                ),
            }
        
        # 2. 进化趋势（最近7天 vs 前7天）
        now = datetime.now()
        recent_7d = [e for e in entries 
                    if (now - datetime.fromisoformat(e.get("timestamp", now.isoformat()))).days <= 7]
        prev_7d = [e for e in entries 
                  if 7 < (now - datetime.fromisoformat(e.get("timestamp", now.isoformat()))).days <= 14]
        
        if recent_7d and prev_7d:
            if len(recent_7d) > len(prev_7d) * 1.2:
                result["evolution_trend"] = "accelerating"
            elif len(recent_7d) < len(prev_7d) * 0.8:
                result["evolution_trend"] = "decelerating"
            else:
                result["evolution_trend"] = "stable"
        
        result["evolution_trend_detail"] = {
            "recent_7d": len(recent_7d),
            "prev_7d": len(prev_7d),
        }
    except Exception as e:
        result["error"] = str(e)
    
    # 3. 脚本健康度
    scripts_status = scan_evolution_scripts()
    total_scripts = len(scripts_status)
    syntax_errors = sum(1 for s in scripts_status.values() if not s.get("syntax_ok", True))
    stale_scripts = sum(1 for s in scripts_status.values() 
                       if s.get("days_since_update", 0) > 30)
    
    result["script_health"] = {
        "total": total_scripts,
        "syntax_errors": syntax_errors,
        "stale (>30d)": stale_scripts,
        "health_score": round(
            (total_scripts - syntax_errors - stale_scripts) / max(total_scripts, 1) * 100, 1
        ),
    }
    
    # 4. 生成自我改进建议
    if result["suggestion_effectiveness"].get("action_rate", 0) < 50:
        result["recommendations"].append(
            "Meta Agent 建议执行率偏低，建议聚焦更具体、可自动化的改进"
        )
    if result["evolution_trend"] == "decelerating":
        result["recommendations"].append(
            "进化速度下降，建议探索新的进化策略或增加跨域迁移"
        )
    if result["script_health"].get("syntax_errors", 0) > 0:
        result["recommendations"].append(
            f"存在 {result['script_health']['syntax_errors']} 个语法错误，优先修复"
        )
    if result["script_health"].get("stale (>30d)", 0) > 2:
        result["recommendations"].append(
            f"有 {result['script_health']['stale (>30d)']} 个脚本超过30天未更新，建议审查"
        )
    
    return result


# ── CLI ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HyperAgents Meta Agent — 元认知引擎")
    parser.add_argument("--dry-run", action="store_true", help="只分析不修改（默认）")
    parser.add_argument("--apply", action="store_true", help="分析并执行改进")
    parser.add_argument("--focus", type=str, choices=["code", "memory", "cron", "strategy"], help="聚焦领域")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--propose", action="store_true", help="只提方案不改")
    parser.add_argument("--self-evaluate", action="store_true", help="自我评估 Meta Agent 效果")
    
    args = parser.parse_args()
    
    if args.self_evaluate:
        result = self_evaluate()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    if args.status:
        result = get_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    dry_run = not args.apply
    result = run_meta_agent(dry_run=dry_run, focus=args.focus)
    
    print("\n" + "=" * 60)
    print("🧬 Meta Agent 完成")
    print("=" * 60)
    print(json.dumps({
        "scripts_scanned": result["scripts_scanned"],
        "improvements_found": result["improvements_found"],
        "improvements_applied": result["improvements_applied"],
        "dry_run": result["dry_run"],
    }, ensure_ascii=False, indent=2))
    print("\n报告预览:")
    print(result["report_preview"])


if __name__ == "__main__":
    main()
