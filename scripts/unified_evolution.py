#!/usr/bin/env python3
"""
unified_evolution.py — 统一进化流水线
一个脚本跑完整个进化闭环，不依赖LLM决定是否执行。

流程：
1. dreaming_engine.py → 采样session，提取模式
2. deep_dream.py → 蒸馏记忆，写入MEMORY.md
3. self_evolve_v2.py → 扫描痛点，自动修复
4. evolution_archive.py → 记录进化档案
5. 生成汇总报告
"""

import json
import os
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

HERMES = Path.home() / '.hermes'
SCRIPTS_DIR = HERMES / 'scripts'
REPORTS_DIR = HERMES / 'reports'
TODAY = date.today().strftime('%Y-%m-%d')


def run_step(name, cmd, timeout=120):
    """Run a step, return (success, output, elapsed)."""
    print(f"\n{'='*60}")
    print(f"▶ Step: {name}")
    print(f"  Command: {cmd}")
    print(f"{'='*60}")
    
    t0 = datetime.now()
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(HERMES)
        )
        elapsed = (datetime.now() - t0).total_seconds()
        
        if result.returncode == 0:
            output = result.stdout.strip()
            # Print last 30 lines of output
            lines = output.split('\n')
            for line in lines[-30:]:
                print(f"  {line}")
            print(f"\n  ✅ {name} 完成 ({elapsed:.1f}s)")
            return True, output, elapsed
        else:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            print(f"  ❌ {name} 失败 (exit={result.returncode}, {elapsed:.1f}s)")
            if stderr:
                print(f"  STDERR: {stderr[:500]}")
            if stdout:
                print(f"  STDOUT: {stdout[-300:]}")
            return False, stderr or stdout, elapsed
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"  ⏰ {name} 超时 ({timeout}s)")
        return False, "timeout", elapsed
    except Exception as e:
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"  ❌ {name} 异常: {e}")
        return False, str(e), elapsed


def main():
    print(f"🧬 统一进化流水线 — {TODAY}")
    print(f"⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    results = {}
    
    # Step 1: Dreaming Engine（记忆策展）
    ok, out, t = run_step(
        "Dreaming Engine（记忆策展）",
        f"python3 {SCRIPTS_DIR}/dreaming_engine.py --days 7 --max-sessions 20",
        timeout=120
    )
    results['dreaming'] = {'ok': ok, 'time': t, 'output_preview': out[:200] if out else ''}
    
    # Step 2: Deep Dream（记忆蒸馏写入MEMORY.md）
    ok, out, t = run_step(
        "Deep Dream（记忆蒸馏）",
        f"python3 {SCRIPTS_DIR}/deep_dream.py",
        timeout=120
    )
    results['deep_dream'] = {'ok': ok, 'time': t, 'output_preview': out[:200] if out else ''}
    
    # Step 3: Self-Evolve（扫描痛点+自动修复）
    ok, out, t = run_step(
        "Self-Evolve v2.1（痛点扫描+自动修复）",
        f"python3 {SCRIPTS_DIR}/self_evolve_v2.py",
        timeout=180
    )
    results['self_evolve'] = {'ok': ok, 'time': t, 'output_preview': out[:200] if out else ''}
    
    # Step 4: Evolution Archive（记录进化档案）
    ok, out, t = run_step(
        "Evolution Archive（记录档案）",
        f"python3 {SCRIPTS_DIR}/evolution_archive.py --record --change \"统一进化流水线 {TODAY}\" --type enhance --domain evolution",
        timeout=30
    )
    results['archive'] = {'ok': ok, 'time': t, 'output_preview': out[:200] if out else ''}
    
    # Summary
    total_time = sum(r['time'] for r in results.values())
    success_count = sum(1 for r in results.values() if r['ok'])
    total_count = len(results)
    
    print(f"\n{'='*60}")
    print(f"📊 进化流水线完成")
    print(f"{'='*60}")
    print(f"  成功: {success_count}/{total_count} 步")
    print(f"  总耗时: {total_time:.1f}s")
    for name, r in results.items():
        icon = "✅" if r['ok'] else "❌"
        print(f"  {icon} {name}: {r['time']:.1f}s")
    
    # Read self_evolve report if it exists
    evolve_report = sorted(Path(HERMES / 'cron/output/self_evolve').glob('*.json'))[-1:] if (HERMES / 'cron/output/self_evolve').exists() else []
    if evolve_report:
        try:
            with open(evolve_report[0]) as f:
                data = json.load(f)
            candidates = data.get('candidates_found', 0)
            auto_done = data.get('auto_done', 0)
            needs_llm = data.get('needs_llm_count', 0)
            print(f"\n  Self-Evolve 详情:")
            print(f"    候选需求: {candidates}")
            print(f"    规则自动处理: {auto_done}")
            print(f"    需LLM兜底: {needs_llm}")
        except Exception:
            pass
    
    # Read dream report if it exists
    dream_report = sorted((HERMES / 'reports/dreams').glob('dream_*.md'))[-1:] if (HERMES / 'reports/dreams').exists() else []
    if dream_report:
        try:
            content = dream_report[0].read_text()
            # Extract key stats
            for line in content.split('\n'):
                if '采样 session' in line or '提取模式' in line or '新增痛点' in line or '用户偏好' in line:
                    print(f"  {line.strip()}")
        except Exception:
            pass
    
    # Write summary to file
    summary = {
        'date': TODAY,
        'timestamp': datetime.now().isoformat(),
        'results': results,
        'success_count': success_count,
        'total_count': total_count,
        'total_time': total_time
    }
    summary_path = REPORTS_DIR / f'unified_evolution_{TODAY.replace("-", "")}.json'
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  📄 汇总报告: {summary_path}")
    
    return success_count == total_count


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"[ERROR] unified_evolution.py failed: {e}", file=sys.stderr)
        sys.exit(1)
