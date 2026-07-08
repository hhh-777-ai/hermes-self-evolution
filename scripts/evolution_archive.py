#!/usr/bin/env python3
"""
evolution_archive.py — 进化档案系统

基于 HyperAgents 的进化档案概念，记录每一代进化的变化和效果。
支持 lineage 追踪、趋势分析、停滞检测、父代选择。

运行方式：
  python3 scripts/evolution_archive.py --record --change "描述" --metrics '{"x":1}'
  python3 scripts/evolution_archive.py --trends [--window 30]
  python3 scripts/evolution_archive.py --select-parents --n 3
  python3 scripts/evolution_archive.py --detect-stagnation
  python3 scripts/evolution_archive.py --status
  python3 scripts/evolution_archive.py --export --format json
"""

import json
import os
import sys
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

HERMES = Path.home() / ".hermes"
ARCHIVE_FILE = HERMES / "knowledge" / "evolution" / "archive.jsonl"
ARCHIVE_INDEX = HERMES / "knowledge" / "evolution" / "archive_index.json"
EVOLUTION_DIR = HERMES / "knowledge" / "evolution"

# 确保目录存在
EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)


def gen_id(change: str) -> str:
    """生成进化条目唯一ID"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    h = hashlib.md5(change.encode()).hexdigest()[:8]
    return f"evo_{ts}_{h}"


def get_git_commit() -> str:
    """获取当前 git commit hash（无 git 时返回 no-git）"""
    return "no-git"


def get_changed_files() -> list:
    """获取变更文件列表（从最近的 git commit 或备份目录）"""
    # 1. 尝试从 git status 获取
    try:
        import subprocess
        r = subprocess.run(["git", "diff", "--name-only", "HEAD~1"], 
                          cwd=str(HERMES), capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")[:10]
    except Exception:
        pass
    
    # 2. 尝试从 meta_agent 备份目录获取
    for subdir in ["meta_agent", "self_modify"]:
        backup_dir = HERMES / "backups" / subdir
        if backup_dir.exists():
            backups = sorted(backup_dir.glob("*.bak_*"), key=lambda f: f.stat().st_mtime, reverse=True)
            if backups:
                return [f.name for f in backups[:5]]
    return []


def record_evolution(
    change: str,
    metrics: dict = None,
    parents: list = None,
    evo_type: str = "code_fix",
    domain: str = "general",
    description: str = "",
    auto_detect_files: bool = True,
) -> dict:
    """
    记录一次进化
    
    Args:
        change: 变更描述
        metrics: 效果指标 {"metric_name": value, ...}
        parents: 父代进化ID列表
        evo_type: 进化类型 (code_fix/config/memory/knowledge/meta)
        domain: 领域 (general/cron/memory/knowledge/trading/infra)
        description: 详细说明
        auto_detect_files: 是否自动检测变更文件
    
    Returns:
        进化条目 dict
    """
    entry = {
        "id": gen_id(change),
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "change": change,
        "description": description or change,
        "type": evo_type,
        "domain": domain,
        "metrics": metrics or {},
        "parents": parents or [],
        "git_commit": get_git_commit(),
        "changed_files": get_changed_files() if auto_detect_files else [],
        "status": "recorded",
        "score": None,  # 后续评估时填充
        "notes": [],
    }
    
    # 追加写入 archive.jsonl
    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    # 更新索引
    _update_index(entry)
    
    return entry


def _update_index(entry: dict):
    """更新档案索引"""
    index = load_index()
    index["last_updated"] = datetime.now().isoformat()
    index["total_entries"] = index.get("total_entries", 0) + 1
    
    # 按类型统计
    evo_type = entry.get("type", "unknown")
    type_key = f"type_{evo_type}"
    index[type_key] = index.get(type_key, 0) + 1
    
    # 按领域统计
    domain = entry.get("domain", "unknown")
    domain_key = f"domain_{domain}"
    index[domain_key] = index.get(domain_key, 0) + 1
    
    # 最近条目
    recent = index.get("recent", [])
    recent.insert(0, {"id": entry["id"], "change": entry["change"], "date": entry["date"]})
    index["recent"] = recent[:50]  # 只保留最近50条
    
    with open(ARCHIVE_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def load_archive() -> list:
    """加载完整进化档案"""
    if not ARCHIVE_FILE.exists():
        return []
    entries = []
    for line in ARCHIVE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_index() -> dict:
    """加载档案索引"""
    if not ARCHIVE_INDEX.exists():
        return {"total_entries": 0, "recent": [], "last_updated": None}
    try:
        return json.loads(ARCHIVE_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {"total_entries": 0, "recent": [], "last_updated": None}


def get_lineage(evo_id: str, max_depth: int = 10) -> list:
    """追踪某个进化的血统链"""
    archive = load_archive()
    by_id = {e["id"]: e for e in archive}
    
    lineage = []
    current = evo_id
    depth = 0
    while current and depth < max_depth:
        entry = by_id.get(current)
        if not entry:
            break
        lineage.append({
            "id": entry["id"],
            "change": entry["change"],
            "date": entry["date"],
            "score": entry.get("score"),
        })
        parents = entry.get("parents", [])
        current = parents[0] if parents else None
        depth += 1
    
    return lineage


def analyze_trends(window: int = 30) -> dict:
    """分析进化趋势"""
    archive = load_archive()
    if not archive:
        return {"status": "empty", "message": "进化档案为空"}
    
    cutoff = datetime.now() - timedelta(days=window)
    recent = [
        e for e in archive
        if datetime.fromisoformat(e["timestamp"]) >= cutoff
    ]
    
    if not recent:
        return {"status": "no_recent", "message": f"最近{window}天无进化记录"}
    
    # 按类型统计
    type_counts = defaultdict(int)
    domain_counts = defaultdict(int)
    daily_counts = defaultdict(int)
    scored_entries = []
    
    for e in recent:
        type_counts[e.get("type", "unknown")] += 1
        domain_counts[e.get("domain", "unknown")] += 1
        daily_counts[e.get("date", "unknown")] += 1
        if e.get("score") is not None:
            scored_entries.append(e)
    
    # 评分趋势
    score_trend = None
    if len(scored_entries) >= 2:
        scores = [e["score"] for e in sorted(scored_entries, key=lambda x: x["timestamp"])]
        first_half = scores[:len(scores)//2]
        second_half = scores[len(scores)//2:]
        avg_first = sum(first_half) / len(first_half) if first_half else 0
        avg_second = sum(second_half) / len(second_half) if second_half else 0
        score_trend = {
            "direction": "improving" if avg_second > avg_first else "declining" if avg_second < avg_first else "stable",
            "avg_first_half": round(avg_first, 3),
            "avg_second_half": round(avg_second, 3),
            "delta": round(avg_second - avg_first, 3),
        }
    
    return {
        "status": "ok",
        "window_days": window,
        "total_entries": len(recent),
        "by_type": dict(type_counts),
        "by_domain": dict(domain_counts),
        "daily_activity": dict(sorted(daily_counts.items())),
        "score_trend": score_trend,
        "avg_score": round(sum(e["score"] for e in scored_entries) / len(scored_entries), 3) if scored_entries else None,
        "scored_count": len(scored_entries),
    }


def select_parents(n: int = 3, strategy: str = "score_prop") -> list:
    """
    选择优秀父代
    
    Args:
        n: 选择数量
        strategy: 选择策略
            - score_prop: 按评分加权随机
            - best: 选评分最高的
            - latest: 选最近的
            - diverse: 选不同类型/领域的
    
    Returns:
        选中的进化条目列表
    """
    archive = load_archive()
    if not archive:
        return []
    
    # 过滤有评分的
    scored = [e for e in archive if e.get("score") is not None]
    
    if strategy == "best":
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:n]
    
    elif strategy == "latest":
        archive.sort(key=lambda x: x["timestamp"], reverse=True)
        return archive[:n]
    
    elif strategy == "diverse":
        # 按类型+领域分组，每组选最好的
        groups = defaultdict(list)
        for e in scored:
            key = f"{e.get('type', 'unknown')}_{e.get('domain', 'unknown')}"
            groups[key].append(e)
        
        selected = []
        for key in sorted(groups.keys()):
            group = sorted(groups[key], key=lambda x: x["score"], reverse=True)
            if group:
                selected.append(group[0])
            if len(selected) >= n:
                break
        return selected[:n]
    
    else:  # score_prop
        if not scored:
            archive.sort(key=lambda x: x["timestamp"], reverse=True)
            return archive[:n]
        # 按评分加权随机选择
        import random
        scores = [max(e["score"], 0.1) for e in scored]
        total = sum(scores)
        weights = [s / total for s in scores]
        indices = random.choices(range(len(scored)), weights=weights, k=min(n, len(scored)))
        return [scored[i] for i in set(indices)]


def detect_stagnation(window: int = 14, threshold: int = 2) -> dict:
    """
    检测进化停滞
    
    Args:
        window: 检测窗口（天）
        threshold: 最少进化次数，低于此值视为停滞
    
    Returns:
        停滞检测结果
    """
    archive = load_archive()
    if not archive:
        return {"stagnant": True, "reason": "进化档案为空", "days_since_last": None}
    
    # 最近窗口期内的进化次数
    cutoff = datetime.now() - timedelta(days=window)
    recent = [
        e for e in archive
        if datetime.fromisoformat(e["timestamp"]) >= cutoff
    ]
    
    # 最后一次进化时间
    last_evo = max(archive, key=lambda x: x["timestamp"])
    last_time = datetime.fromisoformat(last_evo["timestamp"])
    days_since = (datetime.now() - last_time).days
    
    # 评分趋势
    scored = [e for e in recent if e.get("score") is not None]
    no_score_improvement = False
    if len(scored) >= 3:
        scores = [e["score"] for e in sorted(scored, key=lambda x: x["timestamp"])]
        # 检查最近3次是否有提升
        if len(scores) >= 3:
            recent_3 = scores[-3:]
            no_score_improvement = max(recent_3) - min(recent_3) < 0.05
    
    stagnant = False
    reasons = []
    
    if len(recent) < threshold:
        stagnant = True
        reasons.append(f"最近{window}天仅{len(recent)}次进化（阈值{threshold}）")
    
    if days_since > 7:
        stagnant = True
        reasons.append(f"距上次进化已{days_since}天")
    
    if no_score_improvement:
        stagnant = True
        reasons.append("最近评分无明显提升")
    
    return {
        "stagnant": stagnant,
        "reasons": reasons,
        "days_since_last": days_since,
        "recent_count": len(recent),
        "last_evolution": {
            "id": last_evo["id"],
            "change": last_evo["change"],
            "date": last_evo["date"],
        },
        "recommendation": "建议 Meta Agent 审视进化策略" if stagnant else "进化正常",
    }


def evaluate_evolution(evo_id: str, score: float, notes: str = ""):
    """为进化条目评分"""
    if not ARCHIVE_FILE.exists():
        return False
    
    lines = ARCHIVE_FILE.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry["id"] == evo_id:
                entry["score"] = score
                entry["status"] = "evaluated"
                if notes:
                    entry["notes"].append({
                        "text": notes,
                        "timestamp": datetime.now().isoformat(),
                    })
                updated = True
            new_lines.append(json.dumps(entry, ensure_ascii=False))
        except json.JSONDecodeError:
            new_lines.append(line)
    
    if updated:
        ARCHIVE_FILE.write_text("\n".join(new_lines) + "\n")
    
    return updated


def get_status() -> dict:
    """获取档案状态摘要"""
    index = load_index()
    archive = load_archive()
    
    if not archive:
        return {"status": "empty", "total": 0}
    
    # 最近7天
    cutoff = datetime.now() - timedelta(days=7)
    recent_7d = [
        e for e in archive
        if datetime.fromisoformat(e["timestamp"]) >= cutoff
    ]
    
    # 评分统计
    scored = [e for e in archive if e.get("score") is not None]
    avg_score = sum(e["score"] for e in scored) / len(scored) if scored else None
    
    return {
        "status": "ok",
        "total_entries": len(archive),
        "recent_7d": len(recent_7d),
        "scored_entries": len(scored),
        "avg_score": round(avg_score, 3) if avg_score else None,
        "last_updated": index.get("last_updated"),
        "type_distribution": {
            k.replace("type_", ""): v
            for k, v in index.items()
            if k.startswith("type_")
        },
        "domain_distribution": {
            k.replace("domain_", ""): v
            for k, v in index.items()
            if k.startswith("domain_")
        },
    }


def export_archive(fmt: str = "json") -> str:
    """导出档案"""
    archive = load_archive()
    if fmt == "json":
        return json.dumps(archive, ensure_ascii=False, indent=2)
    elif fmt == "summary":
        status = get_status()
        trends = analyze_trends()
        stagnation = detect_stagnation()
        return json.dumps({
            "status": status,
            "trends": trends,
            "stagnation": stagnation,
        }, ensure_ascii=False, indent=2)
    else:
        return json.dumps(archive, ensure_ascii=False, indent=2)


# ── CLI ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="进化档案系统")
    parser.add_argument("--record", action="store_true", help="记录一次进化")
    parser.add_argument("--change", type=str, help="变更描述")
    parser.add_argument("--metrics", type=str, help="效果指标 JSON")
    parser.add_argument("--type", type=str, default="code_fix", help="进化类型")
    parser.add_argument("--domain", type=str, default="general", help="领域")
    parser.add_argument("--description", type=str, default="", help="详细说明")
    parser.add_argument("--parents", type=str, nargs="*", help="父代ID")
    parser.add_argument("--trends", action="store_true", help="分析趋势")
    parser.add_argument("--window", type=int, default=30, help="趋势窗口（天）")
    parser.add_argument("--select-parents", action="store_true", help="选择父代")
    parser.add_argument("--n", type=int, default=3, help="选择数量")
    parser.add_argument("--strategy", type=str, default="score_prop", help="选择策略")
    parser.add_argument("--detect-stagnation", action="store_true", help="检测停滞")
    parser.add_argument("--evaluate", type=str, help="评分进化条目（ID）")
    parser.add_argument("--score", type=float, help="评分值")
    parser.add_argument("--notes", type=str, default="", help="评分备注")
    parser.add_argument("--lineage", type=str, help="追踪血统（ID）")
    parser.add_argument("--status", action="store_true", help="档案状态")
    parser.add_argument("--export", action="store_true", help="导出档案")
    parser.add_argument("--format", type=str, default="json", help="导出格式")
    
    args = parser.parse_args()
    
    if args.record:
        try:
            metrics = json.loads(args.metrics) if args.metrics else {}
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ JSON解析失败: {e}")
            pass
        entry = record_evolution(
            change=args.change,
            metrics=metrics,
            evo_type=args.type,
            domain=args.domain,
            description=args.description,
            parents=args.parents,
        )
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    
    elif args.trends:
        result = analyze_trends(window=args.window)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif args.select_parents:
        parents = select_parents(n=args.n, strategy=args.strategy)
        print(json.dumps(parents, ensure_ascii=False, indent=2))
    
    elif args.detect_stagnation:
        result = detect_stagnation()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif args.evaluate:
        success = evaluate_evolution(args.evaluate, args.score, args.notes)
        print(json.dumps({"success": success, "id": args.evaluate, "score": args.score}))
    
    elif args.lineage:
        lineage = get_lineage(args.lineage)
        print(json.dumps(lineage, ensure_ascii=False, indent=2))
    
    elif args.status:
        result = get_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif args.export:
        print(export_archive(fmt=args.format))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
