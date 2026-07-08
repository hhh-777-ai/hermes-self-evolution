#!/usr/bin/env python3
"""
dreaming_engine.py — 记忆策展引擎

基于 Claude Dreaming 概念的本地化实现。
从历史对话中提取模式，重组记忆层。

核心管线：
1. Session Sampler — 从 session DB 智能采样
2. Pattern Extractor — LLM 提取五类模式
3. Memory Curator — 记忆策展（去重/消歧/折叠）
4. Integration Router — 路由到正确目标层
5. Dream Report — 生成梦境报告

运行方式：
  python3 scripts/dreaming_engine.py [--days 7] [--max-sessions 20] [--dry-run]
  python3 scripts/dreaming_engine.py --status
"""

import json
import os
import re
import sys
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

HERMES = Path.home() / ".hermes"
SESSION_DB = HERMES / "agents" / "main" / "sessions" / "sessions.db"
# 备选路径
if not SESSION_DB.exists():
    for alt in [HERMES / "sessions" / "sessions.db", HERMES / "session.db", HERMES / "state.db"]:
        if alt.exists():
            SESSION_DB = alt
            break
MEMORY_FILE = HERMES / "memories" / "MEMORY.md"
MEMORY_META_FILE = HERMES / "memories" / "MEMORY_META.json"
PAIN_POINTS_FILE = HERMES / "knowledge" / "pain_points.json"
DREAM_REPORTS_DIR = HERMES / "reports" / "dreams"
FACT_STORE_DB = HERMES / "agents" / "main" / "memory" / "memory_store.db"

# 确保目录存在
DREAM_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 五类模式定义 ──
PATTERN_TYPES = {
    "recurring_error": {
        "desc": "重复错误模式",
        "target": "pain_points",
        "importance": 0.9,
        "action": "add_to_pain_points",
    },
    "user_preference": {
        "desc": "用户偏好/纠正",
        "target": "fact_store",
        "importance": 0.95,
        "action": "add_to_fact_store",
    },
    "effective_workflow": {
        "desc": "有效工作流模板",
        "target": "skill",
        "importance": 0.8,
        "action": "propose_skill",
    },
    "stale_info": {
        "desc": "过时信息",
        "target": "memory",
        "importance": 0.6,
        "action": "mark_stale",
    },
    "knowledge_gap": {
        "desc": "知识缺口",
        "target": "night_surf",
        "importance": 0.7,
        "action": "add_to_surf_queue",
    },
}


# ── 1. Session Sampler ──

def sample_sessions(days: int = 7, max_sessions: int = 20) -> list:
    """
    从 session DB 智能采样
    
    优先级：
    1. 工具调用多的 session（说明做了实事）
    2. 出错多的 session（有学习价值）
    3. 用户反馈多的 session（有偏好信号）
    4. 最近的 session（时效性）
    """
    if not SESSION_DB.exists():
        return []
    
    try:
        conn = sqlite3.connect(str(SESSION_DB))
        conn.row_factory = sqlite3.Row
        
        # 计算时间戳（state.db 用 REAL 时间戳）
        cutoff_ts = (datetime.now() - timedelta(days=days)).timestamp()
        
        # 获取候选 session（按 tool_call_count 降序）
        rows = conn.execute("""
            SELECT s.id, s.title, s.started_at, s.tool_call_count, 
                   s.message_count, s.source
            FROM sessions s
            WHERE s.started_at >= ?
            ORDER BY s.tool_call_count DESC, s.message_count DESC
            LIMIT ?
        """, (cutoff_ts, max_sessions * 2)).fetchall()
        
        sessions = []
        for row in rows:
            # 智能采样：前10条(上下文) + 后50条(偏好/纠正信号通常在中后段)
            sid = row["id"]
            total = row["message_count"] or 0
            first_msgs = conn.execute("""
                SELECT role, content, tool_name, timestamp
                FROM messages WHERE session_id = ?
                ORDER BY timestamp LIMIT 10
            """, (sid,)).fetchall()
            if total > 60:
                last_msgs = conn.execute("""
                    SELECT role, content, tool_name, timestamp
                    FROM messages WHERE session_id = ?
                    ORDER BY timestamp DESC LIMIT 50
                """, (sid,)).fetchall()
                last_msgs = list(reversed(last_msgs))  # 恢复时间序
            else:
                last_msgs = []
            # 合并去重（按timestamp）
            seen_ts = {m["timestamp"] for m in first_msgs}
            all_msgs = list(first_msgs)
            for m in last_msgs:
                if m["timestamp"] not in seen_ts:
                    all_msgs.append(m)
                    seen_ts.add(m["timestamp"])
            all_msgs.sort(key=lambda m: m["timestamp"])

            sessions.append({
                "session_id": sid,
                "title": row["title"] or "无标题",
                "created_at": datetime.fromtimestamp(row["started_at"]).isoformat() if row["started_at"] else "",
                "tool_calls": row["tool_call_count"] or 0,
                "msg_count": row["message_count"] or 0,
                "source": row["source"] or "",
                "messages": [
                    {
                        "role": m["role"],
                        "content": (m["content"] or "")[:500],
                        "tool_name": m["tool_name"] or "",
                        "time": datetime.fromtimestamp(m["timestamp"]).isoformat() if m["timestamp"] else "",
                    }
                    for m in all_msgs
                ],
            })
        
        conn.close()
        
        # 按优先级排序
        sessions.sort(key=lambda s: (s["tool_calls"] * 2 + s["msg_count"]), reverse=True)
        return sessions[:max_sessions]
    
    except Exception as e:
        print(f"[ERROR] 采样 session 失败: {e}", file=sys.stderr)
        return []


# ── 2. Pattern Extractor ──

def extract_patterns_rule_based(sessions: list) -> list:
    """
    基于规则的模式提取（不依赖 LLM，快速路径）
    """
    patterns = []
    
    # 收集所有用户消息
    all_user_msgs = []
    for s in sessions:
        for m in s.get("messages", []):
            if m["role"] == "user":
                all_user_msgs.append(m["content"])
    
    # 检测重复错误关键词（过滤正常 tool output 中的 error 字样）
    error_keywords = ["Traceback", "Exception", "traceback", "Error:", "ERROR:", "Failed", "failed"]
    # 排除：tool 返回的正常结果里包含 error 但实际不是错误
    noise_indicators = [
        '"content":', '"output":', '"success":', "tool_result",
        "untrusted_tool_result", "LINE_NUM", "is_binary"
    ]
    error_contexts = []
    for s in sessions:
        for m in s.get("messages", []):
            if m["role"] == "tool":
                content = m["content"]
                # 必须是真正的错误信号，而非正常 tool output
                is_real_error = any(kw in content for kw in error_keywords)
                is_noise = any(ni in content for ni in noise_indicators) and '"error": null' in content
                if is_real_error and not is_noise:
                    ctx = content[:300]
                    error_contexts.append(ctx)
    
    if error_contexts:
        # 聚类相似错误
        error_groups = _cluster_similar(error_contexts, threshold=0.6)
        for group in error_groups:
            if len(group) >= 2:  # 重复出现才算模式
                patterns.append({
                    "type": "recurring_error",
                    "confidence": min(len(group) * 0.2, 0.95),
                    "evidence": group[:3],
                    "description": f"重复错误模式（{len(group)}次）: {group[0][:100]}",
                })
    
    # 检测用户偏好信号
    preference_keywords = ["不要", "别", "记住", "以后", "总是", "应该", "不要做", "我喜欢", "我不喜欢"]
    for msg in all_user_msgs:
        for kw in preference_keywords:
            if kw in msg:
                patterns.append({
                    "type": "user_preference",
                    "confidence": 0.7,
                    "evidence": [msg[:200]],
                    "description": f"用户偏好信号: {msg[:100]}",
                })
                break
    
    # 检测知识缺口（用户问但没答好的）
    question_patterns = ["怎么", "如何", "为什么", "什么是", "能不能", "有没有"]
    for msg in all_user_msgs:
        for qp in question_patterns:
            if qp in msg and "?" in msg:
                patterns.append({
                    "type": "knowledge_gap",
                    "confidence": 0.5,
                    "evidence": [msg[:200]],
                    "description": f"知识缺口: {msg[:100]}",
                })
                break
    
    return patterns


def _cluster_similar(texts: list, threshold: float = 0.6) -> list:
    """简单文本聚类（基于关键词重叠）"""
    if not texts:
        return []
    
    groups = []
    used = set()
    
    for i, t1 in enumerate(texts):
        if i in used:
            continue
        group = [t1]
        used.add(i)
        
        words1 = set(t1.lower().split())
        for j, t2 in enumerate(texts):
            if j in used:
                continue
            words2 = set(t2.lower().split())
            if not words1 or not words2:
                continue
            overlap = len(words1 & words2) / max(len(words1 | words2), 1)
            if overlap >= threshold:
                group.append(t2)
                used.add(j)
        
        groups.append(group)
    
    return groups


# ── 3. Memory Curator ──

def curate_memory(patterns: list, dry_run: bool = False) -> dict:
    """
    记忆策展：将模式转换为结构化操作
    
    Returns:
        {
            "pain_points_added": [...],
            "fact_store_updates": [...],
            "skills_proposed": [...],
            "stale_marked": [...],
            "surf_queue_added": [...],
        }
    """
    result = {
        "pain_points_added": [],
        "fact_store_updates": [],
        "skills_proposed": [],
        "stale_marked": [],
        "surf_queue_added": [],
    }
    
    # 加载现有数据
    pain_points = _load_pain_points()
    existing_pp_descriptions = {p.get("description", "") for p in pain_points.get("pain_points", [])}
    
    for pattern in patterns:
        ptype = pattern.get("type", "unknown")
        desc = pattern.get("description", "")
        confidence = pattern.get("confidence", 0.5)
        
        if confidence < 0.6:
            continue  # 跳过低置信度（减少 noise）
        
        if ptype == "recurring_error":
            # 检查是否已存在
            is_dup = any(_text_similarity(desc, existing) > 0.7 for existing in existing_pp_descriptions)
            if not is_dup:
                entry = {
                    "id": f"pp_{hashlib.md5(desc.encode()).hexdigest()[:8]}",
                    "description": desc,
                    "source": "dreaming_engine",
                    "confidence": confidence,
                    "status": "active",
                    "created": datetime.now().isoformat(),
                    "evidence": pattern.get("evidence", []),
                }
                result["pain_points_added"].append(entry)
                existing_pp_descriptions.add(desc)
                if not dry_run:
                    pain_points.setdefault("pain_points", []).append(entry)
        
        elif ptype == "user_preference":
            entry = {
                "type": "user_pref",
                "content": desc,
                "source": "dreaming_engine",
                "confidence": confidence,
                "created": datetime.now().isoformat(),
            }
            result["fact_store_updates"].append(entry)
        
        elif ptype == "knowledge_gap":
            entry = {
                "query": desc,
                "source": "dreaming_engine",
                "priority": confidence,
                "created": datetime.now().isoformat(),
            }
            result["surf_queue_added"].append(entry)
        
        elif ptype == "effective_workflow":
            entry = {
                "description": desc,
                "source": "dreaming_engine",
                "confidence": confidence,
            }
            result["skills_proposed"].append(entry)
    
    # 写回
    if not dry_run:
        _save_pain_points(pain_points)
        # 持久化 fact_store / skill 候选到文件（供 deep_dream 读取）
        if result["fact_store_updates"] or result["skills_proposed"]:
            curations_file = HERMES / "reports" / "dreams" / f"curations_{datetime.now().strftime('%Y-%m-%d')}.json"
            curations_file.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if curations_file.exists():
                try:
                    existing = json.loads(curations_file.read_text())
                except Exception:
                    pass
            existing.extend(result["fact_store_updates"])
            existing.extend(result["skills_proposed"])
            curations_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2))

    return result


def _load_pain_points() -> dict:
    if PAIN_POINTS_FILE.exists():
        try:
            return json.loads(PAIN_POINTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pain_points": [], "stats": {}}


def _save_pain_points(data: dict):
    PAIN_POINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PAIN_POINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _text_similarity(a: str, b: str) -> float:
    """简单文本相似度"""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


# ── 4. Dream Report ──

def generate_dream_report(
    sessions: list,
    patterns: list,
    curation_result: dict,
    dry_run: bool = False,
) -> str:
    """生成梦境报告"""
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    report = f"""# 🌙 Deep Dream 报告 — {today}

**生成时间**: {now}
**采样 session 数**: {len(sessions)}
**提取模式数**: {len(patterns)}

---

## 📊 Session 采样概览

| Session | 工具调用 | 用户消息 | 时间 |
|---------|---------|---------|------|
"""
    for s in sessions[:10]:
        report += f"| {s['title'][:30]} | {s['tool_calls']} | {s['msg_count']} | {s['created_at'][:10]} |\n"
    
    report += f"""
## 🔍 提取的模式

| 类型 | 置信度 | 描述 |
|------|--------|------|
"""
    for p in patterns[:20]:
        report += f"| {p['type']} | {p.get('confidence', 0):.2f} | {p.get('description', '')[:80]} |\n"
    
    report += f"""
## 🎯 策展结果

- **新增痛点**: {len(curation_result['pain_points_added'])}
- **用户偏好**: {len(curation_result['fact_store_updates'])}
- **技能候选**: {len(curation_result['skills_proposed'])}
- **知识缺口**: {len(curation_result['surf_queue_added'])}
- **过时标记**: {len(curation_result['stale_marked'])}

"""
    
    if curation_result['pain_points_added']:
        report += "### 新增痛点\n"
        for pp in curation_result['pain_points_added']:
            report += f"- 🔴 {pp['description'][:100]}\n"
        report += "\n"
    
    if curation_result['fact_store_updates']:
        report += "### 用户偏好信号\n"
        for fp in curation_result['fact_store_updates']:
            report += f"- 💡 {fp['content'][:100]}\n"
        report += "\n"
    
    if curation_result['surf_queue_added']:
        report += "### 知识缺口（待夜间冲浪补充）\n"
        for kg in curation_result['surf_queue_added']:
            report += f"- ❓ {kg['query'][:100]}\n"
        report += "\n"
    
    report += f"""
---

*由 dreaming_engine.py 自动生成*
"""
    
    if not dry_run:
        report_file = DREAM_REPORTS_DIR / f"dream_{today}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
    
    return report


# ── 5. 主流程 ──

def run_dreaming_pipeline(days: int = 7, max_sessions: int = 20, dry_run: bool = False) -> dict:
    """
    运行完整的 Dreaming 管线
    
    Returns:
        {
            "sessions_sampled": int,
            "patterns_extracted": int,
            "curation_result": dict,
            "report_path": str,
        }
    """
    print(f"[Dreaming] 开始采样最近 {days} 天的 session...")
    sessions = sample_sessions(days=days, max_sessions=max_sessions)
    print(f"[Dreaming] 采样到 {len(sessions)} 个 session")
    
    print("[Dreaming] 提取模式...")
    patterns = extract_patterns_rule_based(sessions)
    print(f"[Dreaming] 提取到 {len(patterns)} 个模式")
    
    print("[Dreaming] 策展记忆...")
    curation = curate_memory(patterns, dry_run=dry_run)
    print(f"[Dreaming] 策展完成: {sum(len(v) for v in curation.values())} 个操作")
    
    print("[Dreaming] 生成报告...")
    report = generate_dream_report(sessions, patterns, curation, dry_run=dry_run)
    
    report_path = str(DREAM_REPORTS_DIR / f"dream_{datetime.now().strftime('%Y-%m-%d')}.md")
    
    return {
        "sessions_sampled": len(sessions),
        "patterns_extracted": len(patterns),
        "curation_result": curation,
        "report_path": report_path if not dry_run else "(dry-run)",
        "report_preview": report[:500],
    }


def get_status() -> dict:
    """获取 Dreaming 引擎状态"""
    # 检查最近报告
    reports = sorted(DREAM_REPORTS_DIR.glob("dream_*.md"), reverse=True)
    
    # 检查 session DB
    session_count = 0
    if SESSION_DB.exists():
        try:
            conn = sqlite3.connect(str(SESSION_DB))
            row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
            session_count = row[0] if row else 0
            conn.close()
        except Exception:
            pass
    
    return {
        "total_sessions": session_count,
        "total_reports": len(reports),
        "latest_report": reports[0].name if reports else None,
        "latest_report_time": datetime.fromtimestamp(reports[0].stat().st_mtime).isoformat() if reports else None,
    }


# ── CLI ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dreaming Engine — 记忆策展引擎")
    parser.add_argument("--days", type=int, default=7, help="采样天数")
    parser.add_argument("--max-sessions", type=int, default=20, help="最大采样 session 数")
    parser.add_argument("--dry-run", action="store_true", help="只分析不写入")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--report-only", action="store_true", help="只生成报告（不采样）")
    
    args = parser.parse_args()
    
    if args.status:
        result = get_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    result = run_dreaming_pipeline(
        days=args.days,
        max_sessions=args.max_sessions,
        dry_run=args.dry_run,
    )
    
    print("\n" + "=" * 60)
    print("🌙 Dreaming Pipeline 完成")
    print("=" * 60)
    print(json.dumps({
        "sessions_sampled": result["sessions_sampled"],
        "patterns_extracted": result["patterns_extracted"],
        "curation_summary": {k: len(v) for k, v in result["curation_result"].items()},
        "report_path": result["report_path"],
    }, ensure_ascii=False, indent=2))
    print("\n报告预览:")
    print(result["report_preview"])


if __name__ == "__main__":
    try:
        main()

    except Exception as _e:
        print(f"[ERROR] dreaming_engine.py failed: {_e}", file=__import__("sys").stderr)
        __import__("sys").exit(1)