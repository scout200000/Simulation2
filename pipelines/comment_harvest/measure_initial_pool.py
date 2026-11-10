# -*- coding: utf-8 -*-
"""统计现有系统「初始舆论池」的真实生成开销。"""
import glob
import json
import os

ROWS = []
for ctl in sorted(glob.glob(r"var/experiments/*/web_control.json")):
    d = json.load(open(ctl, encoding="utf-8"))
    usage = d.get("initial_token_usage")
    exp_dir = os.path.dirname(ctl)
    pool_path = os.path.join(exp_dir, "comment_pool.json")
    n_comments = None
    if os.path.exists(pool_path):
        pool = json.load(open(pool_path, encoding="utf-8"))
        n_comments = len(pool.get("comments") or [])
    ROWS.append(
        {
            "exp": os.path.basename(exp_dir),
            "created": d.get("created_at"),
            "started": d.get("started_at"),
            "comments": n_comments,
            "usage": usage,
        }
    )

ok = [r for r in ROWS if r["usage"] and r["usage"].get("total_tokens")]
print(f"实验总数 {len(ROWS)}，其中记录初始池用量的 {len(ok)} 个\n")
print(f"{'实验':<52} {'评论':>4} {'请求':>4} {'prompt':>7} {'输出':>6} {'缓存':>6} {'合计':>7}")
for r in ROWS:
    u = r["usage"] or {}
    if not u.get("total_tokens"):
        continue
    print(f"{r['exp'][:52]:<52} {r['comments'] or 0:>4} {u.get('logical_request_count', 0):>4} "
          f"{u.get('prompt_tokens', 0):>7} {u.get('completion_tokens', 0):>6} "
          f"{u.get('cached_tokens', 0):>6} {u.get('total_tokens', 0):>7}")

if ok:
    def avg(key):
        return sum(r["usage"].get(key, 0) for r in ok) / len(ok)

    print(f"\n均值：prompt {avg('prompt_tokens'):.0f} / 输出 {avg('completion_tokens'):.0f} / "
          f"缓存 {avg('cached_tokens'):.0f} / 合计 {avg('total_tokens'):.0f} / "
          f"请求 {avg('logical_request_count'):.1f}")

    # 计价：USD / 1M tokens（deepseek 错峰价）
    PIN, PHIT, POUT = 0.15, 0.003, 0.60
    for r in ok:
        u = r["usage"]
        miss = u["prompt_tokens"] - u["cached_tokens"]
        usd = (miss * PIN + u["cached_tokens"] * PHIT + u["completion_tokens"] * POUT) / 1e6
        r["usd"] = usd
    costs = sorted(r["usd"] for r in ok)
    print(f"单次成本 USD：最小 {costs[0]:.6f} / 中位 {costs[len(costs)//2]:.6f} / 最大 {costs[-1]:.6f}")
    print(f"折人民币：¥{costs[0]*7.1:.4f} / ¥{costs[len(costs)//2]*7.1:.4f} / ¥{costs[-1]*7.1:.4f}")

    # 每 100 条评论的归一化成本
    per100 = sorted(r["usd"] / (r["comments"] or 60) * 100 for r in ok)
    print(f"每 100 条评论成本：¥{per100[len(per100)//2]*7.1:.4f}（中位）")

    # 缓存命中率
    rates = [r["usage"]["cached_tokens"] / max(1, r["usage"]["prompt_tokens"]) for r in ok]
    print(f"缓存命中率：{sum(rates)/len(rates):.1%}")

print("\n带时间戳的实验（看初始阶段耗时）：")
for r in ROWS[:4]:
    print(f"  {r['exp'][:50]}  created={r['created']}  started={r['started']}")
