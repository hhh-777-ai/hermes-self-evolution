#!/usr/bin/env python3
"""
自我修复检测脚本 — 每日运行，检测重复出现的痛点
当同一痛点出现 ≥3 次时，输出修补请求供 LLM cron 处理

工作流：
1. 加载 pain_points.json（持久化存储）
2. 扫描当日 errors.log → 提取错误模式
3. 扫描 evolution/thought_*.md → 提取重复主题
4. 更新累计计数
5. 输出 ≥3 次的修补请求到 stdout

设计理念：
- 不决策修补方案（LLM cron 负责）
- 只检测、累计、触发
- 全本地，不依赖 GitHub
"""

import json
import re
import os
import sys
import time
import subprocess
from collections import defaultdict, Counter
from datetime import datetime, timedelta, date
from pathlib import Path

HERMES = Path.home() / '.hermes'
ERROR_LOG = HERMES / 'logs' / 'errors.log'
PAIN_POINTS_FILE = HERMES / 'knowledge' / 'pain_points.json'
EVOLUTION_DIR = HERMES / 'knowledge' / 'evolution'
SCRIPTS_DIR = HERMES / 'scripts'
AGENT_DIR = HERMES / 'hermes-agent'
CONFIG_FILE = HERMES / 'config.yaml'

TODAY = date.today()
TODAY_STR = TODAY.strftime('%Y-%m-%d')
TODAY_COMPACT = TODAY.strftime('%Y%m%d')


# ============================================================
# 1. 数据加载
# ============================================================

def load_pain_points():
    """加载已有的痛点数据"""
    if PAIN_POINTS_FILE.exists():
        try:
            return json.loads(PAIN_POINTS_FILE.read_text())
        except Exception:
            pass
    return {"version": 1, "last_updated": TODAY_STR, "points": []}


def save_pain_points(data):
    """保存痛点数据"""
    data["last_updated"] = TODAY_STR
    PAIN_POINTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  📝 pain_points.json 已更新 ({len(data['points'])} 项)")


# ============================================================
# 2. 错误日志分析
# ============================================================

def parse_error_log():
    """
    扫描今日 errors.log，提取错误模式
    返回 {pattern_key: count} 字典
    """
    if not ERROR_LOG.exists():
        return {}, []
    
    content = ERROR_LOG.read_text()
    today_lines = [l for l in content.split('\n') if l.startswith(TODAY_STR)]
    
    if not today_lines:
        return {}, []
    
    patterns = defaultdict(int)
    raw_errors = []
    
    for line in today_lines:
        # 提取关键错误类型
        err = _extract_error_pattern(line)
        if err:
            patterns[err] += 1
            raw_errors.append((line, err))
    
    return dict(patterns), raw_errors


def _extract_error_pattern(line):
    """
    从一行日志中提取错误模式标识
    注意：过滤已知假阳性：
    - background_review 会阻断 - terminal/execute_code/patch/read_file/write_file/memory → 跳过
    - cron pending_approval (cron_mode: deny 对 python3 -c 的拦截) → 跳过，视为预期行为
    - file-not-found 是 cron job 的正常结果，不是工具本身的 bug → 跳过
    - credential pool / resolve_provider_client → 跳过（预期行为，非工具bug）
    - kanban.db 损坏 → 跳过（需手动 `hermes kanban init`，非自动修复范围）
    - batch_learning_truncation → 单独跟踪
    """
    # 跳过 background_review 拦截 noise
    if 'Background review denied non-whitelisted tool' in line:
        return None
    # 跳过 cron pending_approval (python3 -c 被 cron_mode deny 拦截)
    if 'pending_approval' in line:
        return None
    
    # 跳过 provider credential pool exhausted (预期行为，非工具bug) [auto-evolve]
    if 'credential pool' in line and 'no usable entries' in line:
        return None
    if 'marking openrouter unhealthy' in line:
        return None
    if 'Fallback to openrouter failed' in line:
        return None
    
    # 跳过 resolve_provider_client noise (与credential pool相同根因) [auto-evolve 2026-05-29]
    if 'resolve_provider_client' in line and 'no usable' in line:
        return None
    
    # 跟踪 daily-batch-learning 输出截断 [auto-evolve 2026-05-29]
    if 'Response truncated due to output limit' in line or 'output length limit' in line:
        return 'batch_learning_truncation'
    
    # 跳过 kanban.db 损坏 (需手动 `hermes kanban init`，非自动修复范围) [auto-evolve 2026-05-29]
    if 'kanban.db' in line and 'not a valid SQLite' in line:
        return None
    
    # API 503 - 模型不可用
    if '503' in line and 'capacity limits' in line:
        m = re.search(r'model=(\S+)', line)
        model = m.group(1) if m else 'unknown'
        return f'api_503:{model}'
    
    # API 401 - 认证失败
    if '401' in line and ('API key' in line or 'invalid' in line.lower()):
        m = re.search(r'provider=(\S+)', line)
        provider = m.group(1) if m else 'unknown'
        return f'api_401:{provider}'
    
    # 跳过 cron job File not found（cron job 的正常结果，batch 文件尚未生成）
    if 'File not found' in line and ('cron_' in line or 'CRON' in line.upper()):
        return None
    if 'File not found' in line:
        return None
    
    # 工具执行错误
    if 'tool_executor' in line and 'returned error' in line:
        m = re.search(r'Tool (\S+) returned', line)
        tool = m.group(1) if m else 'unknown'
        return f'tool_error:{tool}'
    
    # 跳过安全拦截导致的工具执行失败 [auto-evolve 2026-06-08]
    if 'pending_approval' in line or 'tirith:' in line:
        return None
    
    # 流式传输中断
    if 'stream_diag' in line or 'Stream drop' in line:
        return 'stream_drop'
    
    # API 连接错误
    if 'APIConnectionError' in line or 'Connection error' in line:
        m = re.search(r'model=(\S+)', line)
        model = m.group(1) if m else 'unknown'
        return f'api_connect:{model}'
    
    # 上下文压缩失败
    if 'Failed to generate context summary' in line:
        return 'context_summary_fail'
    
    return None


# ============================================================
# 3. 进化日志分析
# ============================================================

def scan_evolution_patterns():
    """
    扫描最近 7 天的 evolution/thought logs
    返回重复主题列表
    """
    if not EVOLUTION_DIR.exists():
        return []
    
    # 读取最近 7 天的思考日志
    thought_files = sorted(EVOLUTION_DIR.glob('thought_*.md'))
    recent = [f for f in thought_files if _within_days(f, 7)]
    
    daily_themes = defaultdict(list)  # theme -> [dates]
    
    for tf in recent:
        content = tf.read_text()
        date_str = tf.stem.replace('thought_', '')
        
        # 提取矛盾主题
        for m in re.finditer(r'\[(\w+)\].*矛盾.*严重度', content):
            daily_themes[f'contradiction:{m.group(1)}'].append(date_str)
        
        # 提取冗余
        if re.search(r'冗余.*\d+ 对', content):
            m2 = re.search(r'冗余 \((\d+) 对\)', content)
            if m2 and int(m2.group(1)) >= 2:
                daily_themes['high_redundancy'].append(date_str)
        
        # 提取盲区
        for m in re.finditer(r'\[(\w+)\] .*盲区', content):
            daily_themes[f'knowledge_gap:{m.group(1)}'].append(date_str)
        
        # 提取重复建议类型
        for m in re.finditer(r'\[(\w+)\] ', content):
            sug_type = m.group(1)
            if sug_type in ('resolve_contradiction', 'merge_duplicates', 'fill_gap'):
                daily_themes[f'suggestion:{sug_type}'].append(date_str)
    
    # 统计每个主题出现的天数
    result = []
    for theme, dates in daily_themes.items():
        unique_dates = set(dates)
        if len(unique_dates) >= 2:  # 至少在2天中出现
            result.append({
                'theme': theme,
                'days': len(unique_dates),
                'dates': sorted(unique_dates),
            })
    
    return result


def _within_days(filepath, days):
    """检查文件是否在最近 N 天内修改"""
    try:
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        return (datetime.now() - mtime).days <= days
    except Exception:
        return True  # 如果无法获取，默认包含


# ============================================================
# 4. 痛点累计与更新
# ============================================================

def update_pain_points(pain_data, error_patterns, evolution_patterns):
    """
    将今日检测到的模式与已有痛点合并/累计
    返回: (新增项数, 达到阈值项数)
    """
    existing = {}
    for p in pain_data.get('points', []):
        if 'id' not in p:
            continue
        if p.get('resolved', False):
            continue
        existing[p['id']] = p
    new_count = 0
    trigger_count = 0
    
    # 4a. 处理错误模式
    for pattern, count in error_patterns.items():
        pid = f"err_{pattern.replace(':', '_')}"
        desc = _describe_error_pattern(pattern, count)
        scope = _suggest_scope(pattern)
        fix = _suggest_fix(pattern)
        
        if pid in existing:
            existing[pid]['count'] += count
            existing[pid]['last_seen'] = TODAY_STR
            existing[pid]['context'] = desc
            existing[pid]['suggested_fix_scope'] = scope
            existing[pid]['suggested_fix'] = fix
        else:
            pain_data['points'].append({
                'id': pid,
                'category': _categorize(pattern),
                'description': desc,
                'first_seen': TODAY_STR,
                'count': count,
                'last_seen': TODAY_STR,
                'context': desc,
                'suggested_fix_scope': scope,
                'suggested_fix': fix,
                'resolved': False,
                'resolved_at': None,
                'auto_patch_count': 0,
            })
            new_count += 1
        
        if existing.get(pid, {}).get('count', 0) >= 3 or (pid in existing and existing[pid]['count'] >= 3):
            trigger_count += 1
    
    # 4b. 处理进化模式
    for ep in evolution_patterns:
        pid = f"evo_{ep['theme'].replace(':', '_')}"
        
        if pid in existing:
            # 仅在最近2天没有更新时才累计
            if existing[pid]['last_seen'] < TODAY_STR:
                existing[pid]['count'] += 1
                existing[pid]['last_seen'] = TODAY_STR
                existing[pid]['context'] = f"最近 {ep['days']} 天内在 {len(ep['dates'])} 天重复出现"
        else:
            pain_data['points'].append({
                'id': pid,
                'category': 'knowledge_gap',
                'description': f"进化日志重复模式: {ep['theme']} (出现 {ep['days']} 天)",
                'first_seen': TODAY_STR,
                'count': ep['days'],
                'last_seen': TODAY_STR,
                'context': f"日期: {', '.join(ep['dates'])}",
                'suggested_fix_scope': 'config',
                'suggested_fix': '调整知识采集策略，增加相关模块的覆盖',
                'resolved': False,
                'resolved_at': None,
                'auto_patch_count': 0,
            })
            new_count += 1
        
        if existing.get(pid, {}).get('count', 0) >= 3 or (pid in existing and existing[pid]['count'] >= 3):
            trigger_count += 1
    
    # 4c. 标记超过30天未出现的为自动降级
    for p in pain_data['points']:
        if not p.get('resolved', False) and 'count' in p and p.get('last_seen', '') < (TODAY - __import__('datetime').timedelta(days=30)).strftime('%Y-%m-%d'):
            p['count'] = max(0, p['count'] - 1)  # 缓慢衰减
    
    return new_count, trigger_count


def _categorize(pattern):
    """将错误模式映射到类别"""
    if pattern.startswith('api_503'):
        return 'api_error'
    if pattern.startswith('api_401'):
        return 'api_error'
    if pattern.startswith('tool_error'):
        return 'tool_failure'
    if pattern == 'stream_drop':
        return 'performance'
    if pattern.startswith('api_connect'):
        return 'api_error'
    if pattern == 'context_summary_fail':
        return 'performance'
    if pattern == 'batch_learning_truncation':
        return 'performance'
    return 'script_error'


def _describe_error_pattern(pattern, count):
    """生成人类可读的错误描述"""
    descs = {
        'stream_drop': f'流式传输中断 ({count}次)',
        'context_summary_fail': '上下文压缩失败',
        'batch_learning_truncation': f'batch-learning 输出截断 ({count}次)',
    }
    if pattern.startswith('api_503:'):
        model = pattern.split(':')[1]
        return f'{model} 上游容量不足 ({count}次)'
    if pattern.startswith('api_401:'):
        provider = pattern.split(':')[1]
        return f'{provider} API key 过期或无额度 ({count}次)'
    if pattern.startswith('tool_error:'):
        tool = pattern.split(':')[1]
        return f'{tool} 工具执行失败 ({count}次)'
    if pattern.startswith('api_connect:'):
        model = pattern.split(':')[1]
        return f'{model} 连接超时 ({count}次)'
    return pattern


def _suggest_scope(pattern):
    """建议修补范围"""
    if pattern.startswith('api_') or pattern == 'stream_drop':
        return 'config'
    if pattern.startswith('tool_error'):
        return 'script'
    if pattern == 'context_summary_fail':
        return 'config'
    if pattern == 'batch_learning_truncation':
        return 'config'
    return 'script'


def _suggest_fix(pattern):
    """建议修复方向"""
    fixes = {
        'stream_drop': '增加重试间隔或切换模型',
        'context_summary_fail': '免费模型被上游限速(429)，系统已自动暂停60s重试。如需更稳定可切换付费模型。',
        'batch_learning_truncation': '减少 batch-learning 每次处理量，或拆分任务为多轮',
        'cron_429_rate_limit': '模型API限流(429)，rate_limiter已自动控制并发。如频繁触发，考虑降低该时段cron密度或切换provider。',
        'cron_index_error': '搜索返回空结果导致索引越界，已在batch脚本中加入null_check防御。如持续出现，检查搜索API可用性。',
        'cron_timeout': 'cron任务超时，考虑增加timeout或拆分任务。',
        'cron_auth_fail': 'cron任务认证失败，检查API key是否过期。',
    }
    if pattern.startswith('api_503:'):
        model = pattern.split(':')[1]
        return f'为 {model} 添加备用模型 fallback'
    if pattern.startswith('api_401:'):
        provider = pattern.split(':')[1]
        return f'检查 {provider} API key 是否有效，需手动充值'
    if pattern.startswith('tool_error:'):
        tool = pattern.split(':')[1]
        return f'检查 {tool} 工具的调用参数是否正确'
    if pattern.startswith('api_connect:'):
        return '检查网络连接或增加超时时间'
    return '需要人工评估修复方案'


# ============================================================
# 6. Cron失败模式检测（MOSS auto-scan启发）
# ============================================================

def scan_cron_failures():
    """
    扫描cron输出目录，检测最近的失败模式
    返回: [(job_name, error_type, count), ...]
    """
    import glob
    cron_output = HERMES / 'cron' / 'output'
    if not cron_output.exists():
        return []
    
    failures = defaultdict(lambda: {'count': 0, 'last_error': '', 'last_date': ''})
    
    # 扫描所有cron输出目录
    for job_dir in cron_output.iterdir():
        if not job_dir.is_dir():
            continue
        job_name = job_dir.name[:8]  # 用job_id前8位标识
        
        # 读取最近的输出文件（最多5个）
        outputs = sorted(job_dir.glob('*.md'), reverse=True)[:5]
        for out_file in outputs:
            try:
                content = out_file.read_text(encoding='utf-8', errors='ignore')
                if 'error' not in content.lower() and 'failed' not in content.lower():
                    continue
                
                # 日期从文件名提取
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', out_file.name)
                date_str = date_match.group(1) if date_match else 'unknown'
                
                # 分类错误
                if '429' in content or 'rate limit' in content:
                    err_type = 'cron_429_rate_limit'
                elif 'IndexError' in content or 'list index out of range' in content:
                    err_type = 'cron_index_error'
                elif 'timeout' in content.lower() or 'timed out' in content.lower():
                    err_type = 'cron_timeout'
                elif '401' in content or '403' in content or 'auth' in content.lower():
                    err_type = 'cron_auth_fail'
                else:
                    err_type = 'cron_unknown'
                
                key = f"{job_name}:{err_type}"
                failures[key]['count'] += 1
                failures[key]['last_error'] = err_type
                failures[key]['last_date'] = date_str
                failures[key]['job_name'] = job_name
                
            except Exception:
                continue
    
    # 只返回≥2次的失败
    result = []
    for key, info in failures.items():
        if info['count'] >= 2:
            result.append({
                'job': info['job_name'],
                'error': info['last_error'],
                'count': info['count'],
                'last_date': info['last_date'],
            })
    
    return sorted(result, key=lambda x: -x['count'])


# ============================================================
# 5. 输出修补请求
# ============================================================

def load_dependency_graph():
    """加载系统依赖图谱（迭代2：Layer 2诊断用）"""
    graph_file = HERMES / 'knowledge' / 'system_dependency_graph.json'
    if graph_file.exists():
        try:
            return json.loads(graph_file.read_text())
        except Exception:
            pass
    return None


def load_cron_job_statuses():
    """加载cron任务当前状态，返回 {job_id_prefix: last_status}"""
    jobs_file = HERMES / 'cron' / 'jobs.json'
    if not jobs_file.exists():
        return {}
    try:
        data = json.loads(jobs_file.read_text())
        statuses = {}
        for j in data.get('jobs', []):
            jid = j.get('id', '')[:8]
            statuses[jid] = j.get('last_status', 'unknown')
        return statuses
    except Exception:
        return {}


def is_job_healthy(job_id_prefix, job_statuses):
    """检查cron任务当前是否健康（最近一次运行成功）"""
    return job_statuses.get(job_id_prefix) == 'ok'


def get_impact_scope(graph, changed_component):
    """
    查依赖图谱，返回改动组件的下游影响范围
    迭代2：因果链分析 — 改了A会影响哪些B
    """
    if not graph:
        return []
    nodes = {n['id']: n for n in graph['nodes']}
    edges = graph['edges']

    # 模糊匹配节点
    target_id = ''
    clean = changed_component.replace('.json', '').replace('.yaml', '').replace('.py', '').replace('.sh', '').replace('/', '_')
    for nid, node in nodes.items():
        base = nid.split('_', 1)[1] if '_' in nid else nid
        base_clean = base.replace('.json', '').replace('.yaml', '').replace('.py', '')
        if clean in base_clean or base_clean in clean:
            target_id = nid
            break
    if not target_id:
        return []

    # BFS 遍历下游
    visited = {target_id}
    queue = [(target_id, 0)]
    impacts = []
    while queue:
        current, depth = queue.pop(0)
        if depth > 3:  # 最多3层
            continue
        for e in edges:
            if e.get('source') == current and e.get('target') not in visited:
                visited.add(e['target'])
                dst_node = nodes.get(e['target'], {"label": e['target'], "type": "unknown"})
                impacts.append({
                    'depth': depth + 1,
                    'component': dst_node['label'],
                    'type': dst_node['type'],
                    'relation': e['type'],
                    'description': e.get('description', ''),
                })
                queue.append((e['target'], depth + 1))
    return impacts


def normalize_pain_point(p):
    if 'description' not in p:
        p['description'] = p.get('error') or p.get('context') or p.get('service', '')
    # 为旧格式数据（使用 service+error 字段）生成 id
    if 'id' not in p and 'service' in p and 'error' in p:
        # 基于 service 和 error 生成唯一标识
        import hashlib
        key = f"{p['service']}:{p['error']}"
        p['id'] = f"legacy_{hashlib.md5(key.encode()).hexdigest()[:8]}"
    # 为旧格式数据设置默认 category
    if 'category' not in p:
        if 'service' in p:
            p['category'] = p['service']
        else:
            p['category'] = 'unknown'
    p.setdefault('resolution_note', '')
    p.setdefault('auto_patch_count', 0)
    p.setdefault('resolved_at', None)
    return p


def generate_repair_requests(pain_data, threshold=3):
    """
    筛选出达到阈值的痛点，生成修补请求
    输出到 stdout 供 LLM cron 读取
    迭代2增强：附带影响范围分析
    迭代3增强：检查cron任务当前状态，已恢复的不再推送
    """
    graph = load_dependency_graph()
    job_statuses = load_cron_job_statuses()
    requests = []
    for p in pain_data['points']:
        p = normalize_pain_point(p)
        if p.get('count', 0) >= threshold and not p.get('resolved', False):
            # 迭代3：cron_failure类痛点，检查任务当前状态
            if p.get('category') == 'cron_failure':
                # 从pain point id提取job_id前缀（如 cron_cron_timeout:350b964d）
                # 或从description提取（如 "cron任务350b964d... timeout"）
                job_id = None
                for field in [p.get('id', ''), p.get('description', ''), p.get('context', '')]:
                    m = re.search(r'([0-9a-f]{8,})', field)
                    if m:
                        job_id = m.group(1)[:8]
                        break
                if job_id and is_job_healthy(job_id, job_statuses):
                    # 任务当前健康，跳过此痛点（不生成修补请求）
                    continue

            req = {
                'id': p['id'],
                'category': p['category'],
                'description': p.get('description', ''),
                'count': p['count'],
                'first_seen': p['first_seen'],
                'last_seen': p['last_seen'],
                'suggested_fix_scope': p.get('suggested_fix_scope', ''),
                'suggested_fix': p.get('suggested_fix', ''),
                'context': p.get('context', ''),
            }
            # Layer 2：影响范围分析
            if graph:
                all_impacts = []
                # 方法1：从 context/description 中提取脚本文件名
                ctx = p.get('context', '') + ' ' + p.get('suggested_fix', '') + ' ' + p['description']
                for m in re.findall(r'(\w+\.py|\w+\.sh|\w+\.json|\w+\.yaml)', ctx):
                    impacts = get_impact_scope(graph, m)
                    all_impacts.extend(impacts)
                # 方法2：从 pain point id 中提取（如 tool_error:skill_manage）
                if not all_impacts:
                    # 对 tool_error 类，工具名可能是脚本名
                    tool_match = re.search(r'tool_error:(\w+)', p['id'])
                    if tool_match:
                        impacts = get_impact_scope(graph, f"{tool_match.group(1)}.py")
                        all_impacts.extend(impacts)
                # 方法3：对 config 查 config.yaml 的影响
                if not all_impacts and p.get('suggested_fix_scope') == 'config':
                    impacts = get_impact_scope(graph, 'config.yaml')
                    all_impacts.extend(impacts)

                if all_impacts:
                    # 去重（按 component）
                    seen = set()
                    unique = []
                    for imp in all_impacts:
                        key = imp['component']
                        if key not in seen:
                            seen.add(key)
                            unique.append(imp)
                    req['impact_scope'] = unique[:10]  # 最多10个

            requests.append(req)
    
    return requests


def print_report(error_patterns, evolution_results, new_count, trigger_count, requests):
    """打印结构化报告（供 LLM cron 解析）"""
    
    print("=" * 60)
    print(f"🔧 自我修复检测报告 - {TODAY_STR}")
    print("=" * 60)
    print()
    
    # 今日错误统计
    print(f"📊 今日错误模式 ({len(error_patterns)} 种)")
    if error_patterns:
        for pattern, count in sorted(error_patterns.items(), key=lambda x: -x[1]):
            print(f"   {pattern}: {count}次")
    else:
        print("   今日无新错误")
    print()
    
    # 进化模式统计
    print(f"🧠 进化日志重复模式 ({len(evolution_results)} 项)")
    for ep in evolution_results:
        print(f"   {ep['theme']}: {ep['days']}天出现")
    print()
    
    # 痛点总览
    print(f"📋 痛点累计: 新增 {new_count} 项, 达到阈值 {trigger_count} 项")
    print()
    
    # 修补请求
    if requests:
        print("🚨 修补请求 (阈值 ≥3):")
        print(json.dumps(requests, ensure_ascii=False, indent=2))
        print()
        print(f"💡 共 {len(requests)} 项待修补")
    else:
        print("✅ 无达到阈值的痛点，无需修补")
    
    print("=" * 60)


# ============================================================
# 主函数
# ============================================================

def main():
    print(f"🔧 自我修复检测 - {TODAY_STR}")
    print(f"   错误日志: {ERROR_LOG}")
    print(f"   痛点文件: {PAIN_POINTS_FILE}")
    print(f"   进化日志: {EVOLUTION_DIR}")
    print()
    
    # 1. 加载现有痛点
    pain_data = load_pain_points()
    print(f"📂 加载 {len(pain_data['points'])} 项已有痛点")
    
    # 2. 扫描错误日志
    error_patterns, raw_errors = parse_error_log()
    if error_patterns:
        print(f"⚠️  检测到 {len(error_patterns)} 种错误模式:")
        for p, c in sorted(error_patterns.items(), key=lambda x: -x[1]):
            print(f"   {p}: {c}次")
    else:
        print(f"✅ 今日无新错误")
    
    # 3b. 扫描cron失败模式（MOSS auto-scan启发）
    new_count = 0  # [auto-evolve] 初始化计数器，修复 UnboundLocalError
    cron_failures = scan_cron_failures()
    if cron_failures:
        print(f"🔄 Cron失败模式 ({len(cron_failures)} 项):")
        for cf in cron_failures:
            print(f"   [{cf['job']}] {cf['error']}: {cf['count']}次 (最近: {cf['last_date']})")
        # 将cron失败加入痛点
        for cf in cron_failures:
            pid = f"cron_{cf['error']}"
            desc = f"cron任务{cf['job'][:8]}... {cf['error']} ({cf['count']}次)"
            if pid in {p['id']: p for p in pain_data['points'] if 'id' in p}:
                existing = {p['id']: p for p in pain_data['points'] if 'id' in p}
                existing[pid]['count'] += cf['count']
                existing[pid]['last_seen'] = cf['last_date']
            else:
                pain_data['points'].append({
                    'id': pid,
                    'category': 'cron_failure',
                    'description': desc,
                    'first_seen': cf['last_date'],
                    'count': cf['count'],
                    'last_seen': cf['last_date'],
                    'context': f"最近失败日期: {cf['last_date']}",
                    'suggested_fix_scope': 'script',
                    'suggested_fix': _suggest_fix(cf['error']),
                    'resolved': False,
                    'resolved_at': None,
                    'auto_patch_count': 0,
                })
                new_count += 1
    else:
        print(f"✅ Cron无重复失败模式")
    
    # 4. 扫描进化日志
    evolution_patterns = scan_evolution_patterns()
    if evolution_patterns:
        print(f"🧠 进化日志发现 {len(evolution_patterns)} 个重复模式:")
        for ep in evolution_patterns:
            print(f"   {ep['theme']}: 在 {ep['days']} 天中出现")
    else:
        print(f"✅ 进化日志无重复模式")
    
    # 4. 更新痛点累计
    upd_new_count, trigger_count = update_pain_points(
        pain_data, error_patterns, evolution_patterns
    )
    new_count += upd_new_count  # [auto-evolve] 合并cron新增计数和错误模式新增计数
    save_pain_points(pain_data)
    
    # 5. 生成修补请求
    requests = generate_repair_requests(pain_data, threshold=3)
    
    # 6. 打印报告
    print()
    print_report(error_patterns, evolution_patterns, new_count, trigger_count, requests)
    
    # 7. 如果有修补请求，以 JSON 格式输出供 cron LLM 读取
    if requests:
        print()
        print("=== REPAIR_REQUEST_BEGIN ===")
        print(json.dumps(requests, ensure_ascii=False, indent=2))
        print("=== REPAIR_REQUEST_END ===")

        # 8. 自动执行修复（A类直接做，B类备份后做，C类仅报告）
        print()
        print("=== AUTO_REPAIR_BEGIN ===")
        try:
            repair_result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'auto_repair.py')],
                input=json.dumps(requests, ensure_ascii=False),
                capture_output=True, text=True, timeout=60
            )
            print(repair_result.stdout)
            if repair_result.stderr:
                print(f"⚠️ auto_repair stderr: {repair_result.stderr}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("⏰ auto_repair 超时（60s），跳过自动修复")
        except Exception as e:
            print(f"⚠️ auto_repair 调用失败: {e}")
        print("=== AUTO_REPAIR_END ===")


if __name__ == '__main__':
    try:
        main()

    except Exception as _e:
        print(f"[ERROR] self_heal.py failed: {_e}", file=__import__("sys").stderr)
        __import__("sys").exit(1)