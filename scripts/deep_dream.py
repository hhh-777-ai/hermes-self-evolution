#!/usr/bin/env python3
"""
Deep Dream 记忆蒸馏 v2.0
==========================
基于 Nemori 预测误差蒸馏 + AutoMem 分类体系

核心原则（v2.0 升级）：
1. 预测误差蒸馏：只保留"现有记忆无法预测的新信息"
2. 分类体系：Decision/Pattern/Correction/Insight/Event 五类
3. 重要性评分：0.3-0.9，用户纠正 > 决策 > 模式 > 洞察 > 事件
4. 关联链接：新记忆自动链接到相关旧记忆
5. 冲突检测：新记忆是否与旧记忆矛盾，标记 INVALIDATED_BY
6. 遗忘机制：低重要性 + 长时间未访问 → 自动衰减

流程：
1. 采集当天数据（cron 输出、痛点、知识库新增、session 摘要）
2. 与现有记忆对比，计算"预测误差"（新信息量）
3. 按五类分类，评分重要性
4. 检测冲突和关联
5. 写入 MEMORY.md（带类型和分数元数据）
6. 重建记忆 GPU 索引
7. 生成 Deep Dream 报告

运行方式：
  python3 scripts/deep_dream.py [--date YYYY-MM-DD] [--dry-run] [--verbose]
"""
import json
import os
import re
import sys
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

HERMES = Path.home() / ".hermes"
MEMORY_FILE = HERMES / "memories" / "MEMORY.md"
MEMORY_META_FILE = HERMES / "memories" / "MEMORY_META.json"
PAIN_POINTS_FILE = HERMES / "knowledge" / "pain_points.json"
KB_INDEX_FILE = HERMES / "knowledge" / "knowledge_index.json"
CRON_OUTPUT_DIR = HERMES / "cron" / "output"
SESSIONS_DIR = HERMES / "agents" / "main" / "sessions"
REPORTS_DIR = HERMES / "reports"

# ── 记忆类型定义 ──
MEMORY_TYPES = {
    "Decision":   {"importance_range": (0.85, 0.95), "desc": "架构/库/方案选择，长期引用"},
    "Pattern":    {"importance_range": (0.75, 0.85), "desc": "最佳实践/可复用方法，跨项目有用"},
    "Correction": {"importance_range": (0.90, 0.95), "desc": "用户纠正/偏好，最强个性化信号"},
    "Insight":    {"importance_range": (0.70, 0.80), "desc": "Bug修复/关键学习，有时效性"},
    "Event":      {"importance_range": (0.30, 0.60), "desc": "系统事件/统计，短期有用"},
}

# ── 工具函数 ──

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def get_yesterday():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

def read_file_safe(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return default

def load_memory_index():
    """加载记忆元数据索引"""
    content = read_file_safe(MEMORY_META_FILE, "{}")
    try:
        return json.loads(content)
    except Exception:
        return {"memories": [], "associations": [], "stats": {}}

def save_memory_index(index):
    """保存记忆元数据索引"""
    with open(MEMORY_META_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def parse_memory_entries(content):
    """解析 MEMORY.md 为结构化条目"""
    entries = []
    # 按 § 分隔符分割
    raw_entries = content.split("§")
    for raw in raw_entries:
        raw = raw.strip()
        if not raw:
            continue
        # 提取类型标签
        mem_type = "Event"  # 默认
        importance = 0.5
        m = re.match(r"【(\w+)】", raw)
        if m:
            label = m.group(1)
            type_map = {
                "决策": "Decision", "决定": "Decision", "选择": "Decision",
                "模式": "Pattern", "方法": "Pattern", "实践": "Pattern",
                "纠正": "Correction", "偏好": "Correction", "用户": "Correction",
                "洞察": "Insight", "学习": "Insight", "发现": "Insight",
                "事件": "Event", "系统": "Event", "运行": "Event",
            }
            mem_type = type_map.get(label, "Event")
            importance = MEMORY_TYPES[mem_type]["importance_range"][0]
        entries.append({
            "content": raw,
            "type": mem_type,
            "importance": importance,
            "core": raw[raw.index("】")+1:].strip() if "】" in raw else raw.strip()
        })
    return entries

def compute_novelty(new_text, existing_entries, threshold=0.6):
    """
    计算新文本的"预测误差"（新颖度）
    基于与现有记忆的核心文本重叠度
    返回 0-1，越高越新颖
    """
    if not existing_entries:
        return 1.0
    
    new_core = new_text.strip()
    if "】" in new_core:
        new_core = new_core[new_core.index("】")+1:].strip()
    
    # 简单的关键词重叠度计算
    new_words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', new_core.lower()))
    if not new_words:
        return 0.5
    
    max_overlap = 0
    for entry in existing_entries:
        existing_core = entry.get("core", "")
        existing_words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', existing_core.lower()))
        if not existing_words:
            continue
        overlap = len(new_words & existing_words) / max(len(new_words), 1)
        max_overlap = max(max_overlap, overlap)
    
    novelty = 1 - max_overlap
    return novelty

def classify_memory(text):
    """
    自动分类记忆类型
    返回 (type, importance)
    """
    text_lower = text.lower()
    
    # Correction: 用户纠正/偏好
    correction_keywords = ["用户", "贤民", "纠正", "偏好", "不要", "必须", "应该", "期望"]
    if any(kw in text for kw in correction_keywords) and ("用户" in text or "贤民" in text):
        return "Correction", 0.92
    
    # Decision: 决策/选择
    decision_keywords = ["选择", "决定", "方案", "采用", "切换", "升级", "放弃", "配置"]
    if any(kw in text for kw in decision_keywords):
        return "Decision", 0.88
    
    # Pattern: 模式/方法/教训
    pattern_keywords = ["教训", "方法", "模式", "流程", "规范", "原则", "规则", "最佳"]
    if any(kw in text for kw in pattern_keywords):
        return "Pattern", 0.80
    
    # Insight: 发现/学习
    insight_keywords = ["发现", "学习", "研究", "分析", "验证", "测试", "结果"]
    if any(kw in text for kw in insight_keywords):
        return "Insight", 0.75
    
    # Event: 默认
    return "Event", 0.45

def detect_conflicts(new_text, existing_entries):
    """
    检测新记忆是否与旧记忆矛盾
    返回冲突的旧记忆索引列表
    """
    conflicts = []
    conflict_pairs = [
        (["不要", "不能", "禁止"], ["应该", "需要", "必须"]),
        (["切换为", "改为", "换成"], ["保持", "继续", "沿用"]),
        (["已修复", "已解决"], ["未解决", "待修复", "error"]),
    ]
    
    for i, entry in enumerate(existing_entries):
        for neg, pos in conflict_pairs:
            new_has_neg = any(kw in new_text for kw in neg)
            new_has_pos = any(kw in new_text for kw in pos)
            old_has_neg = any(kw in entry["core"] for kw in neg)
            old_has_pos = any(kw in entry["core"] for kw in pos)
            if (new_has_pos and old_has_neg) or (new_has_neg and old_has_pos):
                # 检查是否涉及同一主题
                new_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', new_text))
                old_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', entry["core"]))
                if len(new_words & old_words) >= 2:
                    conflicts.append(i)
                    break
    return conflicts

def memory_exists_in_file(content, new_entry, threshold=0.7):
    """检查新条目是否已存在（模糊匹配）"""
    new_core = new_entry.strip()
    if "】" in new_core:
        new_core = new_core[new_core.index("】")+1:].strip()
    
    # 精确匹配
    if new_core[:50] in content:
        return True
    
    # 关键词重叠度
    new_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', new_core))
    if not new_words:
        return False
    
    existing_entries = parse_memory_entries(content)
    for entry in existing_entries:
        existing_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', entry["core"]))
        if new_words and existing_words:
            overlap = len(new_words & existing_words) / max(len(new_words), 1)
            if overlap > threshold:
                return True
    return False

def append_to_memory(new_entries: list[dict]):
    """追加新条目到 MEMORY.md（带元数据）"""
    content = read_file_safe(MEMORY_FILE)
    added = []
    for entry in new_entries:
        text = entry["text"]
        if not memory_exists_in_file(content, text):
            mem_type = entry.get("type", "Event")
            importance = entry.get("importance", 0.5)
            # 写入格式：【类型】内容 §
            formatted = f"【{mem_type}】{text}"
            with open(MEMORY_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{formatted}\n§\n")
            added.append({
                "text": text[:80],
                "type": mem_type,
                "importance": importance,
                "novelty": entry.get("novelty", 0)
            })
            content += formatted  # 更新 content 避免重复
    return added

# ── 数据采集 ──

def collect_cron_outputs(date_str: str) -> list[dict]:
    """采集指定日期的所有 cron 任务输出（只取 Response 部分，跳过 prompt 模板）"""
    results = []
    if not CRON_OUTPUT_DIR.exists():
        return results
    
    for job_dir in CRON_OUTPUT_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        for output_file in job_dir.iterdir():
            if date_str.replace("-", "") not in output_file.name and date_str not in output_file.name:
                continue
            content = read_file_safe(output_file)
            if not content.strip():
                continue
            
            # ── 关键改进：分离 prompt 和实际输出 ──
            # 策略1: 找 "## Response" 或 "## Output" 标记后的内容
            response_content = ""
            for marker in ["## Response\n", "## Output\n", "## Result\n", "---\n\n"]:
                if marker in content:
                    response_content = content.split(marker, 1)[-1]
                    break
            
            # 策略2: 如果没找到标记，取后 50% 且过滤模板行
            if not response_content:
                lines = content.split("\n")
                tail = lines[len(lines) // 2:]
                content_lines = []
                for line in tail:
                    # 跳过模板行
                    if re.match(r'^#{1,6}\s', line):  # ### 开头的标题
                        continue
                    if re.match(r'^\*\*Step\s+\d+', line):  # **Step 1:** 模板
                        continue
                    if re.match(r'^---+$', line):  # 分隔线
                        continue
                    if re.match(r'^##\s+(Input|Instructions|Format|Output)', line):
                        continue
                    content_lines.append(line)
                response_content = "\n".join(content_lines)
            
            if len(response_content.strip()) > 80:
                results.append({
                    "job": job_dir.name,
                    "file": output_file.name,
                    "content": response_content[:3000]  # 限制长度
                })
    return results
def collect_pain_points() -> list[dict]:
    """采集未解决的痛点"""
    content = read_file_safe(PAIN_POINTS_FILE, "[]")
    try:
        points = json.loads(content)
        return [p for p in points if not p.get("resolved", False)]
    except Exception:
        return []

def collect_kb_new_entries(date_str: str) -> list[dict]:
    """采集知识库当天新增条目"""
    content = read_file_safe(KB_INDEX_FILE, "{}")
    try:
        data = json.loads(content)
        entries = data.get("knowledge", data) if isinstance(data, dict) else data
        return [e for e in entries if e.get("date", "") == date_str.replace("-", "")]
    except Exception:
        return []

def collect_session_summaries(date_str: str) -> list[str]:
    """采集当天的 session 对话摘要"""
    summaries = []
    if not SESSIONS_DIR.exists():
        return summaries
    for f in SESSIONS_DIR.iterdir():
        if date_str in f.name and f.suffix == ".md":
            content = read_file_safe(f)
            if content.strip():
                summaries.append(content[:1500])
    return summaries

# ── 智能蒸馏引擎 ──

def distill_memories(date_str, cron_outputs, pain_points, kb_new, session_summaries, existing_entries, verbose=False):
    """
    核心蒸馏引擎
    基于预测误差 + 分类 + 冲突检测
    """
    candidates = []
    
    # ── 从 cron 输出提取候选记忆 ──
    # 只关注系统内部事件，过滤外部新闻/市场信息
    # 外部新闻特征：公司名+产品名+版本号、市场数据、股价、新闻标题
    EXTERNAL_NEWS_PATTERNS = [
        re.compile(r'(NVIDIA|AMD|Intel|Apple|Google|Microsoft|OpenAI|Anthropic|Meta|字节|阿里|腾讯|百度|华为)[\w\s]*(发布|推出|升级|更新|财报|股价|市值)'),
        re.compile(r'(ChatGPT|Codex|GPT|Claude|Gemini|LLaMA|DeepSeek)[\w\s]*(发布|推出|更新|合体|升级)'),
        re.compile(r'(v\d+\.\d+|版本 \d+\.\d+[\.\d]*)'),  # 版本号
        re.compile(r'(\d+亿|\d+万|\d+\.\d+%|\$\d+|\¥\d+)'),  # 大数字/金额/百分比
        re.compile(r'(stars|GitHub|开源|stars)'),
        re.compile(r'(板块|轮动|资金|配置|蓝筹|半导体|AI股|科技股)'),
    ]
    
    def is_external_news(text):
        """判断是否为外部新闻（不应作为系统记忆）"""
        for p in EXTERNAL_NEWS_PATTERNS:
            if p.search(text):
                return True
        return False
    
    # 模板行过滤规则
    TEMPLATE_PATTERNS = [
        re.compile(r'^#{1,6}\s+'),          # ### 标题
        re.compile(r'^\*{2}Step\s+\d+'),     # **Step 1:**
        re.compile(r'^---+$'),               # 分隔线
        re.compile(r'^##\s+(Input|Instructions|Format|Output|Response)'),
        re.compile(r'^\[.*\]$'),             # [占位符]
        re.compile(r'^请(生成|输出|分析)'),   # 中文指令
        re.compile(r'^Please\s+(generate|output)', re.I),
        re.compile(r'^\*\*.*\*\*:\s*$'),     # **标签:** (空内容)
        re.compile(r'^-{3,}$'),              # --- 短横线
    ]
    
    def is_template_line(line):
        """判断是否为模板行"""
        for p in TEMPLATE_PATTERNS:
            if p.match(line.strip()):
                return True
        return False
    
    for cron in cron_outputs:
        content = cron["content"]
        job = cron["job"]
        
        # 提取关键句子
        sentences = re.split(r'[。！？\n]', content)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 15 or len(sent) > 200:
                continue
            
            # 跳过模板行
            if is_template_line(sent):
                continue
            
            # 跳过纯日志/进度信息
            skip_keywords = ["进度", "开始", "完成", "Step", "===", "---", "SILENT",
                           "✅", "⚪", "❌", "🔄", "📊", "🧠", "💭", "✍️", "🔍"]
            if any(kw in sent for kw in skip_keywords) and len(sent) < 30:
                continue
            
            # 只保留包含结论性信息的句子
            signal_keywords = ["成功", "失败", "发现", "修复", "更新", "切换", "配置",
                             "错误", "问题", "解决", "优化", "升级", "部署", "测试",
                             "验证", "确认", "决定", "选择", "采用", "放弃", "用户",
                             "贤民", "必须", "不要", "应该", "需要", "已经", "已"]
            if not any(kw in sent for kw in signal_keywords):
                continue
            
            # 额外过滤：跳过外部新闻（市场信息、产品发布等）
            if is_external_news(sent):
                continue
            
            # 额外过滤：跳过 cron 内部 meta 信息
            meta_features = ["改进建议", "已应用", "query新增", "配置版本",
                           "skill_manage 错误", "最高频模式", "人工评估根因",
                           "重要性=", "新颖度=", "候选记忆", "去重后", "过滤后"]
            if any(pf in sent for pf in meta_features):
                continue
            
            # 额外过滤：跳过包含 prompt 特征的句子
            prompt_features = ["格式：", "输出格式", "请按照", "根据以下", "---",
                             "### ", "## ", "**分析", "**数据", "关键发现：[", "待改进：[",
                             "预期改善", "今天最重要的", "发现了什么问题"]
            if any(pf in sent for pf in prompt_features):
                continue
            
            # 质量评分：过滤低质量候选
            quality_score = 1.0
            # 包含占位符 [xxx] → 质量低
            if re.search(r'\[.*\]', sent):
                quality_score -= 0.5
            # 纯数字+百分比的句子 → 可能是编造的数据
            if re.match(r'^[\d.%+\- ]+$', sent):
                quality_score -= 0.3
            # 太短（<20字）且无具体信息
            if len(sent) < 20:
                quality_score -= 0.2
            # 包含"预期"、"预计"、"可能"等不确定词 → 降低
            uncertain_words = ["预期", "预计", "可能", "或许", "大概", "应该能"]
            if any(w in sent for w in uncertain_words):
                quality_score -= 0.2
            
            if quality_score < 0.5:
                continue
            
            novelty = compute_novelty(sent, existing_entries)
            mem_type, importance = classify_memory(sent)
            
            # 质量加权重要性
            importance *= quality_score
            
            # 只保留高新颖度（>0.5）的句子
            if novelty > 0.5:
                candidates.append({
                    "text": sent,
                    "source": f"cron:{job[:30]}",
                    "type": mem_type,
                    "importance": importance * novelty,
                    "novelty": novelty,
                })
    
    # ── 从痛点提取候选记忆 ──
    for point in pain_points:
        desc = point.get("desc", "")
        if not desc:
            continue
        novelty = compute_novelty(desc, existing_entries)
        severity = point.get("severity", "warning")
        importance = 0.85 if severity == "error" else 0.70
        candidates.append({
            "text": f"未解决痛点: {desc[:100]}",
            "source": "pain_points",
            "type": "Insight",
            "importance": importance * novelty,
            "novelty": novelty,
        })
    
    # ── 从知识库新增提取候选记忆 ──
    if len(kb_new) > 0:
        topics = set(e.get("topic", "") for e in kb_new[:20] if e.get("topic"))
        titles = [e.get("title", "")[:40] for e in kb_new[:5] if e.get("title")]
        summary = f"知识库新增 {len(kb_new)} 条，领域：{'、'.join(topics)}"
        if titles:
            summary += f"。包括：{'；'.join(titles)}"
        novelty = compute_novelty(summary, existing_entries)
        candidates.append({
            "text": summary,
            "source": "knowledge_base",
            "type": "Event",
            "importance": 0.50 * novelty,
            "novelty": novelty,
        })
    
    # ── 从 session 摘要提取候选记忆 ──
    for summary in session_summaries:
        # 提取关键决策/发现
        sentences = re.split(r'[。！？\n]', summary)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 20 or len(sent) > 200:
                continue
            signal_keywords = ["决定", "选择", "发现", "确认", "修复", "优化", "部署",
                             "用户", "贤民", "要求", "期望", "授权"]
            if not any(kw in sent for kw in signal_keywords):
                continue
            novelty = compute_novelty(sent, existing_entries)
            if novelty > 0.5:
                mem_type, importance = classify_memory(sent)
                candidates.append({
                    "text": sent,
                    "source": "session",
                    "type": mem_type,
                    "importance": importance * novelty,
                    "novelty": novelty,
                })
    
    # ── 去重 + 排序 + 过滤 ──
    # 按重要性降序
    candidates.sort(key=lambda x: x["importance"], reverse=True)
    
    # 去重：同类型且文本相似的只保留最高的
    seen_texts = []
    unique_candidates = []
    for c in candidates:
        is_dup = False
        for seen in seen_texts:
            # 简单去重：共享 60% 以上关键词
            c_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', c["text"]))
            s_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', seen))
            if c_words and s_words and len(c_words & s_words) / max(len(c_words), 1) > 0.6:
                is_dup = True
                break
        if not is_dup:
            seen_texts.append(c["text"])
            unique_candidates.append(c)
    
    # 过滤：重要性 > 0.3 且新颖度 > 0.4
    filtered = [c for c in unique_candidates if c["importance"] > 0.3 and c["novelty"] > 0.4]
    
    # 最多保留 8 条（避免记忆膨胀）
    top_candidates = filtered[:8]
    
    if verbose:
        print(f"\n  📋 候选记忆分析：")
        print(f"    原始候选: {len(candidates)} 条")
        print(f"    去重后: {len(unique_candidates)} 条")
        print(f"    过滤后: {len(filtered)} 条")
        print(f"    最终保留: {len(top_candidates)} 条")
        for c in top_candidates:
            print(f"    [{c['type']}] 重要性={c['importance']:.2f} 新颖度={c['novelty']:.2f} | {c['text'][:60]}")
    
    return top_candidates

# ── 主蒸馏逻辑 ──

def run_deep_dream(date_str: str = None, dry_run: bool = False, verbose: bool = False):
    """执行 Deep Dream 蒸馏 v2.0"""
    if date_str is None:
        date_str = get_yesterday()
    
    print(f"🌙 Deep Dream 蒸馏 v2.0 开始：{date_str}")
    print("=" * 60)
    
    # 1. 采集数据
    print("\n📊 Step 1: 采集数据...")
    cron_outputs = collect_cron_outputs(date_str)
    print(f"  cron 输出: {len(cron_outputs)} 条")
    pain_points = collect_pain_points()
    print(f"  未解决痛点: {len(pain_points)} 条")
    kb_new = collect_kb_new_entries(date_str)
    print(f"  知识库新增: {len(kb_new)} 条")
    session_summaries = collect_session_summaries(date_str)
    print(f"  session 摘要: {len(session_summaries)} 条")
    
    # 2. 加载现有记忆
    print("\n🧠 Step 2: 加载现有记忆...")
    memory_content = read_file_safe(MEMORY_FILE)
    existing_entries = parse_memory_entries(memory_content)
    print(f"  现有记忆: {len(existing_entries)} 条")
    
    # 3. 智能蒸馏
    print("\n💭 Step 3: 智能蒸馏（预测误差 + 分类 + 冲突检测）...")
    candidates = distill_memories(
        date_str, cron_outputs, pain_points, kb_new, session_summaries,
        existing_entries, verbose=verbose
    )
    
    if not candidates:
        print("  ⚠️ 无高质量候选记忆（当天可能无重要事件）")
        # 即使没有高质量候选，也记录系统运行事件
        if cron_outputs:
            candidates = [{
                "text": f"{date_str} 系统运行正常，{len(cron_outputs)} 个 cron 任务产生输出",
                "source": "system",
                "type": "Event",
                "importance": 0.35,
                "novelty": 0.3,
            }]
            print(f"  ℹ️ 生成 1 条系统运行记录")
    
    # 4. 冲突检测
    print("\n🔍 Step 4: 冲突检测...")
    memory_index = load_memory_index()
    conflict_count = 0
    for c in candidates:
        conflicts = detect_conflicts(c["text"], existing_entries)
        if conflicts:
            c["conflicts"] = conflicts
            conflict_count += 1
            if verbose:
                print(f"    ⚠️ 冲突: {c['text'][:50]} ↔ 已有记忆 {conflicts}")
    print(f"  检测到 {conflict_count} 个冲突")
    
    # 5. 写入 MEMORY.md
    if dry_run:
        print(f"\n🔍 [DRY RUN] 将写入 {len(candidates)} 条记忆：")
        for c in candidates:
            print(f"  [{c['type']}] 重要性={c['importance']:.2f} | {c['text'][:70]}")
        added = []
    else:
        print(f"\n✍️ Step 5: 写入 MEMORY.md...")
        added = append_to_memory(candidates)
        print(f"  新增 {len(added)} 条（去重后）")
        for a in added:
            print(f"    [{a['type']}] {a['text'][:60]}")
    
    # 6. 生成报告
    report = f"""# Deep Dream 蒸馏报告 v2.0 - {date_str}

## 数据采集
- Cron 输出: {len(cron_outputs)} 条
- 未解决痛点: {len(pain_points)} 条
- 知识库新增: {len(kb_new)} 条
- Session 摘要: {len(session_summaries)} 条

## 蒸馏结果
- 候选记忆: {len(candidates)} 条
- 冲突检测: {conflict_count} 个
- 去重后新增: {len(added)} 条

## 新增记忆条目
{chr(10).join(f"- [{a['type']}] 重要性={a.get('importance',0):.2f} | {a['text']}" for a in added) if added else "（无新增）"}

## 记忆类型分布
{chr(10).join(f"- {t}: {sum(1 for a in added if a['type']==t)} 条" for t in MEMORY_TYPES)}

---
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
版本: Deep Dream v2.0
"""
    
    report_file = REPORTS_DIR / f"deep_dream_{date_str.replace('-', '')}.md"
    if not dry_run:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(report, encoding="utf-8")
        print(f"  📄 报告已保存: {report_file}")
    
    # 7. 重建记忆 GPU 索引
    if added and not dry_run:
        print("\n🔄 Step 6: 重建记忆 GPU 索引...")
        try:
            sys.path.insert(0, str(HERMES / "scripts"))
            from memory_gpu import build_index
            count = build_index(events_only=False)
            print(f"  ✅ 记忆 GPU 索引已重建：{count} 条")
        except Exception as e:
            print(f"  ⚠️ 记忆 GPU 索引重建失败：{e}")
    
    # 8. 重建事件图谱
    if added and not dry_run:
        print("\n🔄 Step 7: 重建事件图谱...")
        try:
            sys.path.insert(0, str(HERMES / "scripts"))
            from memory_graph import build_graph
            graph = build_graph()
            print(f"  ✅ 事件图谱已重建：{graph['stats']['total_events']} 事件 / {graph['stats']['total_relations']} 关联")
        except Exception as e:
            print(f"  ⚠️ 事件图谱重建失败：{e}")

    print(f"\n✅ Deep Dream 蒸馏 v2.0 完成：{date_str}")
    return len(added)

# ── CLI ──

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deep Dream 记忆蒸馏 v2.0")
    parser.add_argument("--date", help="蒸馏日期 (YYYY-MM-DD)，默认昨天")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()
    
    date_str = args.date or get_yesterday()
    count = run_deep_dream(date_str, dry_run=args.dry_run, verbose=args.verbose)
    sys.exit(0 if count >= 0 else 1)
