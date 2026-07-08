#!/usr/bin/env python3
"""
evolution_self_eval.py — HyperAgents 自评估系统

评估维度：
1. ROI 计算（进化效率指标）
2. 停滞检测（系统是否在退化）
3. 改进建议（基于数据驱动的诊断）

运行方式：
  python3 scripts/evolution_self_eval.py          # 生成报告
  python3 scripts/evolution_self_eval.py --quiet  # 只输出 JSON
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter

HERMES = Path.home() / ".hermes"
ARCHIVE_FILE = HERMES / "knowledge" / "evolution" / "archive.jsonl"
REPORT_FILE = HERMES / "knowledge" / "evolution" / "self_eval_report.json"
REPORTS_DIR = HERMES / "reports" / "self_eval"

# 阈值
STAGNATION_DAYS = 7          # 超过 N 天无实际修改 = 停滞
STAGNATION_MIN_ENTRIES = 3   # 至少 N 条记录才开始判断
SUCCESS_STATUS = "recorded"  # 成功状态


def load_entries(days=None):
    """加载进化档案条目"""
    if not ARCHIVE_FILE.exists():
        return []

    entries = []
    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)

    for line in ARCHIVE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if cutoff:
                try:
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts < cutoff:
                        continue
                except (ValueError, KeyError):
                    pass
            entries.append(entry)
        except json.JSONDecodeError:
            continue

    return entries


def compute_roi(entries):
    """
    计算进化效率指标

    ROI = 实际产出 / 投入
    由于没有 token/时间投入数据，用以下代理指标：
    - actionability: 有 changed_files 的条目占比
    - coverage: 涉及的不同 domain 数
    - consistency: 平均每天条目数
    """
    if not entries:
        return {"status": "no_data"}

    total = len(entries)
    actionable = sum(1 for e in entries if e.get("changed_files"))
    by_type = Counter(e.get("type", "?") for e in entries)
    by_domain = Counter(e.get("domain", "?") for e in entries)

    # 时间范围
    timestamps = []
    for e in entries:
        try:
            timestamps.append(datetime.fromisoformat(e["timestamp"]))
        except (ValueError, KeyError):
            pass

    if timestamps:
        earliest = min(timestamps)
        latest = max(timestamps)
        span_days = max(1, (latest - earliest).days)
        per_day = round(len(entries) / span_days, 2)
    else:
        span_days = 1
        per_day = 0
        earliest = latest = datetime.now()

    # 是否有改变（status=recorded + changed_files非空）
    successful = sum(1 for e in entries
                     if e.get("status") == SUCCESS_STATUS and e.get("changed_files"))

    return {
        "status": "ok",
        "total_entries": total,
        "actionable_entries": actionable,
        "successful_modifications": successful,
        "actionability_rate": round(actionable / total, 3) if total else 0,
        "success_rate": round(successful / total, 3) if total else 0,
        "entries_per_day": per_day,
        "time_span_days": span_days,
        "date_range": {
            "from": earliest.strftime("%Y-%m-%d"),
            "to": latest.strftime("%Y-%m-%d"),
        },
        "by_type": dict(by_type.most_common()),
        "by_domain": dict(by_domain.most_common()),
        "unique_domains": len(by_domain),
        "unique_types": len(by_type),
    }


def detect_stagnation(entries):
    """
    检测系统是否在停滞

    停滞信号：
    1. 最近 N 天无任何条目
    2. 最近 N 天无条目有 changed_files
    3. 连续 M 次进化产出 0 个 high 建议（通过检查 change 描述中的关键词）
    """
    if not entries:
        return {"is_stagnant": True, "reason": "无进化记录"}

    now = datetime.now()
    recent_7d = [e for e in entries
                 if _days_ago(e.get("timestamp"), now) <= 7]
    recent_7d_actionable = [e for e in recent_7d if e.get("changed_files")]
    recent_30d = [e for e in entries
                  if _days_ago(e.get("timestamp"), now) <= 30]

    signals = []

    # 信号1: 7天内无任何记录
    if not recent_7d:
        signals.append("连续 7 天无任何进化记录")
    # 信号2: 7天内无实际修改
    elif not recent_7d_actionable:
        signals.append(f"最近 7 天有 {len(recent_7d)} 条记录但 0 个实际代码修改")

    # 信号3: 所有条目都是 test/meta 类型（无 code_fix/real change）
    if recent_30d:
        non_meta = [e for e in recent_30d if e.get("type") not in ("test", "meta")]
        if not non_meta:
            signals.append("最近 30 天所有记录都是 test/meta 类型，无实际改进")

    # 信号4: 不同 target 数 = 0（不改不同的文件）
    all_targets = set()
    for e in recent_30d:
        for f in e.get("changed_files", []):
            all_targets.add(f)
    if recent_30d and len(all_targets) == 0:
        signals.append("最近 30 天未修改任何不同文件")

    return {
        "is_stagnant": len(signals) > 0,
        "signals": signals,
        "recent_7d_entries": len(recent_7d),
        "recent_7d_actionable": len(recent_7d_actionable),
        "recent_30d_entries": len(recent_30d),
        "unique_targets_30d": len(all_targets),
    }


def _days_ago(timestamp_str, now):
    """计算距今天数"""
    try:
        ts = datetime.fromisoformat(timestamp_str)
        return (now - ts).days
    except (ValueError, TypeError, KeyError):
        return 999


def generate_recommendations(roi, stagnation):
    """基于评估结果生成改进建议"""
    recs = []

    if roi.get("status") == "no_data":
        recs.append({
            "priority": "high",
            "issue": "进化档案为空",
            "action": "检查 record_evolution() 是否在 self_evolve 中被调用",
        })
        return recs

    # 基于 actionability
    actionability = roi.get("actionability_rate", 0)
    if actionability < 0.3:
        recs.append({
            "priority": "medium",
            "issue": f"进化可执行率低 ({actionability:.0%})",
            "action": "大量产出是 meta/test 类型的记录，建议提高 code_fix 类产出的比例",
            "suggestion": "在 propose_meta_improvements 中优先产出可执行目标而非 review_suggestions",
        })
    elif actionability > 0.7:
        recs.append({
            "priority": "info",
            "issue": None,
            "action": f"进化可执行率良好 ({actionability:.0%})",
        })

    # 基于 stagnation
    if stagnation.get("is_stagnant"):
        for sig in stagnation.get("signals", []):
            recs.append({
                "priority": "high",
                "issue": f"停滞信号: {sig}",
                "action": "检查进化运行日志，确认 Meta Agent cron 正常运行；扩展候选扫描范围",
            })

    # 基于 consistency
    per_day = roi.get("entries_per_day", 0)
    if per_day < 0.5:
        recs.append({
            "priority": "low",
            "issue": f"进化频率低 ({per_day} 条/天)",
            "action": "当前进化频率符合按需进化原则，非异常",
        })

    # 基于 diversity
    if roi.get("unique_domains", 0) <= 2:
        recs.append({
            "priority": "medium",
            "issue": f"进化覆盖领域单一 ({roi['unique_domains']} 个域)",
            "action": "建议拓展进化候选源（如知识库优化、记忆层改进等）",
        })

    if not recs:
        recs.append({
            "priority": "info",
            "issue": None,
            "action": "系统运行状态健康",
        })

    return recs


def generate_report(quiet=False):
    """生成完整的自评估报告"""
    entries_all = load_entries()
    entries_30d = load_entries(days=30)
    entries_7d = load_entries(days=7)

    roi_all = compute_roi(entries_all)
    roi_30d = compute_roi(entries_30d)
    stagnation = detect_stagnation(entries_all)
    recommendations = generate_recommendations(roi_30d, stagnation)

    report = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "roi": {
            "all_time": roi_all,
            "last_30d": roi_30d,
            "last_7d": compute_roi(entries_7d),
        },
        "stagnation": stagnation,
        "recommendations": recommendations,
    }

    # 保存报告
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"eval_{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 也保存为 latest
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quiet:
        _print_report(report)

    return report


def _print_report(report):
    """格式化打印报告"""
    today = report["date"]
    print(f"\n[HyperAgents 自评估报告] {today}")
    print("=" * 60)

    # ROI
    roi = report["roi"]["last_30d"]
    if roi.get("status") == "ok":
        print(f"\n最近30天进化效率")
        print(f"  总记录: {roi['total_entries']}")
        print(f"  成功修改: {roi['successful_modifications']}")
        print(f"  可执行率: {roi['actionability_rate']:.0%}")
        print(f"  成功修改率: {roi['success_rate']:.0%}")
        print(f"  频率: {roi['entries_per_day']} 条/天")
        print(f"  覆盖域: {roi['unique_domains']} 个 {list(roi['by_domain'].keys())}")
        print(f"  类型分布: {roi['by_type']}")
    else:
        print(f"\nROI: 无数据")

    # Stagnation
    stag = report["stagnation"]
    print(f"\n停滞检测")
    if stag["is_stagnant"]:
        print(f"  [WARNING] 检测到停滞!")
        for sig in stag.get("signals", []):
            print(f"    - {sig}")
    else:
        print(f"  [OK] 运行正常 (7天{stag['recent_7d_entries']}条, {stag['recent_7d_actionable']}条有修改)")

    # Recommendations
    recs = report["recommendations"]
    print(f"\n改进建议 ({len(recs)} 条)")
    for r in recs:
        p = r["priority"]
        label = {"high": "[!]", "medium": "[~]", "low": "[.]", "info": "[i]"}.get(p, "[?]")
        print(f"  {label} [{p}] {r['action']}")
        if r.get("issue"):
            print(f"     问题: {r['issue']}")

    print(f"\n报告已保存: knowledge/evolution/self_eval_report.json")
    print("=" * 60)


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv
    report = generate_report(quiet=quiet)

    # 输出 JSON 供 cron agent 解析
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
