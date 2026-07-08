#!/usr/bin/env python3
"""
cross_domain_transfer.py — 跨域知识迁移引擎

基于 HyperAgents 的 meta-level improvements 可跨域迁移核心发现：
"编码领域的经验可以指导配置修复，脚本优化经验可以指导流程优化"

核心思路：
1. 从进化档案中提取已验证的有效改进模式
2. 分析改进的"元模式"（不是具体操作，而是操作的模式）
3. 将元模式应用到新的领域

举例：
- 编码域："修复 bare except → except Exception" 
  元模式："消除过于宽泛的捕获/匹配"
  配置域迁移：检查是否有过于宽泛的配置匹配规则

- 编码域："重复代码 → 提取函数"
  元模式："识别重复模式并抽象"
  脚本域迁移：检查是否有重复的脚本逻辑可以合并

运行方式：
  python3 scripts/cross_domain_transfer.py [--dry-run] [--source-domain code] [--target-domain config]
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

HERMES = Path.home() / ".hermes"
ARCHIVE_FILE = HERMES / "knowledge" / "evolution" / "archive.jsonl"
TRANSFER_LOG = HERMES / "knowledge" / "evolution" / "transfer_log.json"

# 领域定义
DOMAINS = {
    "code": {
        "name": "代码改进",
        "patterns": ["修复", "bug", "error", "语法", "import", "except", "exception",
                     "变量", "函数", "类", "循环", "条件"],
        "file_patterns": ["*.py", "*.js", "*.ts"],
    },
    "config": {
        "name": "配置优化",
        "patterns": ["config", "yaml", "json", "配置", "参数", "设置", "timeout",
                     "schedule", "retry", "threshold"],
        "file_patterns": ["*.yaml", "*.yml", "*.json", "*.toml"],
    },
    "cron": {
        "name": "定时任务优化",
        "patterns": ["cron", "schedule", "timeout", "频率", "重试", "限流",
                     "429", "rate_limit", "interval"],
        "file_patterns": ["*cron*", "*schedule*"],
    },
    "memory": {
        "name": "记忆层优化",
        "patterns": ["memory", "MEMORY", "记忆", "fact", "knowledge", "过时",
                     "stale", "去重", "冲突"],
        "file_patterns": ["*memory*", "*knowledge*"],
    },
    "script": {
        "name": "脚本优化",
        "patterns": ["script", "脚本", "自动化", "pipeline", "流程", "步骤",
                     "输入", "输出", "参数"],
        "file_patterns": ["*.py", "*.sh"],
    },
}

# 迁移规则：从源域的改进模式 → 目标域的检查策略
TRANSFER_RULES = [
    {
        "name": "bare_except_fix",
        "source_domain": "code",
        "pattern": r"except\s*:",
        "description": "消除过于宽泛的异常捕获",
        "target_checks": [
            {
                "domain": "config",
                "check": "检查是否有过于宽泛的配置匹配（如通配符规则）",
                "pattern": r"\*\*|wildcard|通配|all",
            },
            {
                "domain": "script",
                "check": "检查是否有过于宽泛的输入匹配",
                "pattern": r"except\s*:|except\s+Exception.*pass",
            },
        ],
    },
    {
        "name": "duplicate_detection",
        "source_domain": "code",
        "pattern": r"(重复|duplicate|copy.?paste|复制粘贴)",
        "description": "识别重复模式并抽象",
        "target_checks": [
            {
                "domain": "script",
                "check": "检查重复的脚本逻辑（相似度>0.8的脚本）",
                "pattern": r"similarity|>0\.8|重复逻辑",
            },
            {
                "domain": "cron",
                "check": "检查功能重复的 cron 任务",
                "pattern": r"重复.*任务|.*cron.*重复",
            },
        ],
    },
    {
        "name": "hardcoded_value",
        "source_domain": "code",
        "pattern": r"(hardcod|硬编码|magic number|魔法数字)",
        "description": "消除硬编码值",
        "target_checks": [
            {
                "domain": "config",
                "check": "检查配置文件中的硬编码值（应提取为变量）",
                "pattern": r"(localhost|127\.0\.0\.1|\d{4,})",
            },
            {
                "domain": "cron",
                "check": "检查 cron 表达式中的硬编码时间是否合理",
                "pattern": r"\d+\s+\d+\s+\*\s+\*",
            },
        ],
    },
    {
        "name": "timeout_missing",
        "source_domain": "code",
        "pattern": r"(timeout|超时|超时)",
        "description": "确保所有外部调用都有超时",
        "target_checks": [
            {
                "domain": "script",
                "check": "检查所有 HTTP/子进程/外部调用是否有 timeout",
                "pattern": r"\.get\(|\.post\(|\.run\(|subprocess\.run\(",
            },
            {
                "domain": "cron",
                "check": "检查 cron 任务是否有超时设置",
                "pattern": r"timeout|max.*runtime",
            },
        ],
    },
    {
        "name": "error_handling",
        "source_domain": "code",
        "pattern": r"(error|错误|失败|fail|exception)",
        "description": "确保错误被正确处理",
        "target_checks": [
            {
                "domain": "cron",
                "check": "检查 cron 任务是否有错误通知/降级机制",
                "pattern": r"error.*notify|降级|fallback|retry",
            },
            {
                "domain": "memory",
                "check": "检查记忆写入是否有错误恢复（防崩溃丢失）",
                "pattern": r"try.*write|write.*error|memory.*fail",
            },
        ],
    },
]


def load_archive(days=30):
    """加载进化档案"""
    if not ARCHIVE_FILE.exists():
        return []
    
    entries = []
    cutoff = datetime.now() - timedelta(days=days)
    
    for line in ARCHIVE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if datetime.fromisoformat(entry["timestamp"]) >= cutoff:
                entries.append(entry)
        except (json.JSONDecodeError, ValueError) as e:
            continue
    
    return entries


def extract_patterns_from_archive(entries):
    """从进化档案中提取改进模式"""
    patterns = []
    
    for entry in entries:
        change = entry.get("change", "")
        desc = entry.get("description", "")
        entry_type = entry.get("type", "unknown")
        domain = entry.get("domain", "unknown")
        
        for rule in TRANSFER_RULES:
            if re.search(rule["pattern"], change, re.IGNORECASE) or \
               re.search(rule["pattern"], desc, re.IGNORECASE):
                patterns.append({
                    "rule_name": rule["name"],
                    "description": rule["description"],
                    "matched_change": change[:100],
                    "source_domain": rule["source_domain"],
                    "origin_domain": domain,
                    "entry_id": entry.get("id", ""),
                    "target_checks": rule["target_checks"],
                })
    
    return patterns


def check_target_domain(patterns, target_domain):
    """在目标域中检查是否存在类似问题"""
    results = []
    domain_info = DOMAINS.get(target_domain, {})
    
    if not domain_info:
        return results
    
    scripts_dir = HERMES / "scripts"
    
    for pattern in patterns:
        for check in pattern.get("target_checks", []):
            if check["domain"] != target_domain:
                continue
            
            # 扫描相关文件
            issues = []
            for file_pattern in domain_info.get("file_patterns", []):
                for filepath in scripts_dir.glob(file_pattern):
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        if re.search(check["pattern"], content, re.IGNORECASE):
                            # 找出匹配的行
                            for i, line in enumerate(content.splitlines(), 1):
                                if re.search(check["pattern"], line, re.IGNORECASE):
                                    issues.append({
                                        "file": filepath.name,
                                        "line": i,
                                        "content": line.strip()[:80],
                                    })
                    except Exception:
                        continue
            
            if issues:
                # 去重：同一文件只保留首次匹配
                seen_files = set()
                unique_issues = []
                for iss in issues:
                    if iss["file"] not in seen_files:
                        seen_files.add(iss["file"])
                        unique_issues.append(iss)
                results.append({
                    "rule": pattern["rule_name"],
                    "source": f"{pattern['origin_domain']} → {target_domain}",
                    "check_description": check["check"],
                    "issues_found": len(unique_issues),
                    "issues": unique_issues[:5],  # 最多显示 5 个
                })
    
    return results


def run_transfer_analysis(dry_run=True):
    """运行完整的跨域迁移分析"""
    print("🔄 跨域知识迁移分析")
    print("=" * 60)
    
    # 1. 加载进化档案
    entries = load_archive(days=30)
    print(f"\n📚 加载了 {len(entries)} 条进化记录")
    
    if not entries:
        print("⚠️ 进化档案为空，无法提取模式")
        return {"status": "empty_archive"}
    
    # 2. 提取改进模式（去重：同一 rule_name + source_domain 只保留一条）
    raw_patterns = extract_patterns_from_archive(entries)
    seen = set()
    patterns = []
    for p in raw_patterns:
        key = (p["rule_name"], p["source_domain"])
        if key not in seen:
            seen.add(key)
            patterns.append(p)
    if len(raw_patterns) > len(patterns):
        print(f"🔍 提取到 {len(raw_patterns)} 个模式，去重后 {len(patterns)} 个唯一模式")
    else:
        print(f"🔍 提取到 {len(patterns)} 个可迁移模式")
    
    if not patterns:
        print("⚠️ 未发现可迁移的改进模式")
        return {"status": "no_patterns"}
    
    # 3. 检查每个目标域
    all_results = {}
    for target_domain, domain_info in DOMAINS.items():
        results = check_target_domain(patterns, target_domain)
        if results:
            all_results[target_domain] = results
            print(f"\n🎯 [{domain_info['name']}] 发现 {len(results)} 个可迁移建议:")
            for r in results:
                print(f"   [{r['rule']}] {r['source']}: {r['check_description'][:60]}")
                print(f"     发现 {r['issues_found']} 处匹配")
                for issue in r["issues"][:3]:
                    print(f"     - {issue['file']}:{issue['line']} {issue['content']}")
    
    if not all_results:
        print("\n✨ 目标域均无明显可迁移项（已接近最优）")
    
    # 4. 记录迁移日志
    log = {
        "timestamp": datetime.now().isoformat(),
        "patterns_found": len(patterns),
        "domains_checked": len(DOMAINS),
        "transferable_results": {k: len(v) for k, v in all_results.items()},
        "dry_run": dry_run,
    }
    
    if not dry_run:
        _save_transfer_log(log)
    
    return log


def _save_transfer_log(log):
    """保存迁移日志"""
    logs = []
    if TRANSFER_LOG.exists():
        try:
            logs = json.loads(TRANSFER_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    logs.append(log)
    TRANSFER_LOG.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="跨域知识迁移引擎")
    parser.add_argument("--dry-run", action="store_true", help="只分析不写入（默认）")
    parser.add_argument("--apply", action="store_true", help="分析并记录迁移建议")
    args = parser.parse_args()
    
    dry_run = not args.apply
    result = run_transfer_analysis(dry_run=dry_run)
    
    print(f"\n{'='*60}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
