"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _invalid_num(val: object) -> bool:
    return val is None or isinstance(val, bool) or (isinstance(val, (int, float)) and (math.isnan(val) or math.isinf(val)))


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate."""
    problems: list[str] = []

    pr_metrics = pr.get("metrics") or {}
    for k, v in pr_metrics.items():
        if _invalid_num(v):
            problems.append(f"metric {k} is invalid ({v!r})")
    for m in spec.get("metrics") or []:
        mid = m["id"]
        if mid not in pr_metrics or _invalid_num(pr_metrics.get(mid)):
            problems.append(f"spec metric {mid} missing or invalid in PR metrics")

    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty ({len(pr['evaluator_failures'])})")

    pr_rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    pr_manifest = pr.get("manifest") or {}
    base_manifest = base.get("manifest") or {}

    expected_len = int(pr_manifest.get("items") or 0) * len(pr_manifest.get("seeds") or [])
    if len(pr_rows) != expected_len:
        problems.append(f"len(rows)={len(pr_rows)} != manifest items*seeds ({expected_len})")
    if len(pr_rows) != len(base_rows):
        problems.append(f"len(pr.rows)={len(pr_rows)} != len(base.rows)={len(base_rows)}")

    pr_pairs = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    base_pairs = [(r.get("item_id"), r.get("seed")) for r in base_rows]
    if len(set(pr_pairs)) != len(pr_pairs):
        problems.append("duplicate (item_id, seed) rows in PR")
    if set(pr_pairs) != set(base_pairs):
        problems.append("PR (item_id, seed) set differs from baseline")
    if pr_manifest.get("seeds") != base_manifest.get("seeds") or pr_manifest.get("items") != base_manifest.get("items"):
        problems.append("PR manifest items/seeds differ from baseline")

    row_metric_ids = [
        m["id"]
        for m in (spec.get("metrics") or [])
        if m["id"] in GRADERS or any(m["id"] in r for r in pr_rows) or any(m["id"] in r for r in base_rows)
    ]
    for r in pr_rows:
        for mid in row_metric_ids:
            v = r.get(mid)
            if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has missing/NaN value for {mid}")
                break

    base_slices_by_pair = {(r.get("item_id"), r.get("seed")): sorted(r.get("slices") or []) for r in base_rows}
    for r in pr_rows:
        pair = (r.get("item_id"), r.get("seed"))
        if pair in base_slices_by_pair and sorted(r.get("slices") or []) != base_slices_by_pair[pair]:
            problems.append(f"slice tags modified for {pair[0]}@{pair[1]}")
            break

    if pr_rows and not problems:
        for m in spec.get("metrics") or []:
            mid = m["id"]
            if mid not in row_metric_ids:
                continue
            vals = [r.get(mid) for r in pr_rows if isinstance(r.get(mid), bool)]
            if len(vals) == len(pr_rows) and mid in pr_metrics and not _invalid_num(pr_metrics[mid]):
                if mid in ("secret_leak", "approval_bypass") or m.get("kind") == "safety":
                    expected_metric = sum(vals)
                else:
                    expected_metric = round(sum(vals) / len(vals), 4)
                if abs(float(pr_metrics[mid]) - float(expected_metric)) > 1e-3:
                    problems.append(f"metric {mid}={pr_metrics[mid]} disagrees with rows ({expected_metric})")

    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_m = {m["id"]: m for m in base_spec.get("metrics") or []}
        cur_m = {m["id"]: m for m in spec.get("metrics") or []}
        for mid, bm in base_m.items():
            if mid not in cur_m:
                problems.append(f"ratchet: metric {mid} removed")
                continue
            cm = cur_m[mid]
            if bm.get("blocking") and not cm.get("blocking"):
                problems.append(f"ratchet: metric {mid} became non-blocking")
            bth = bm.get("threshold") or {}
            cth = cm.get("threshold") or {}
            if "min" in bth and ("min" not in cth or cth["min"] < bth["min"]):
                problems.append(f"ratchet: metric {mid} min threshold lowered ({cth.get('min')} < {bth['min']})")
            if "max" in bth and ("max" not in cth or cth["max"] > bth["max"]):
                problems.append(f"ratchet: metric {mid} max threshold raised ({cth.get('max')} > {bth['max']})")
            if "max_increase" in bth and ("max_increase" not in cth or cth["max_increase"] > bth["max_increase"]):
                problems.append(f"ratchet: metric {mid} max_increase raised")
            if bth.get("no_significant_drop") and not cth.get("no_significant_drop"):
                problems.append(f"ratchet: metric {mid} dropped no_significant_drop")

        base_s = {(s["name"], s["metric"]): s for s in base_spec.get("slices") or []}
        cur_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
        for key, bs_item in base_s.items():
            if key not in cur_s:
                problems.append(f"ratchet: slice {key[0]}/{key[1]} removed")
                continue
            cs_item = cur_s[key]
            if bs_item.get("blocking") and not cs_item.get("blocking"):
                problems.append(f"ratchet: slice {key[0]}/{key[1]} became non-blocking")
            if "min" in bs_item and ("min" not in cs_item or cs_item["min"] < bs_item["min"]):
                problems.append(f"ratchet: slice {key[0]}/{key[1]} min lowered")
            if "max" in bs_item and ("max" not in cs_item or cs_item["max"] > bs_item["max"]):
                problems.append(f"ratchet: slice {key[0]}/{key[1]} max raised")
            if bs_item.get("no_significant_drop") and not cs_item.get("no_significant_drop"):
                problems.append(f"ratchet: slice {key[0]}/{key[1]} dropped no_significant_drop")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        sname, mid = s["name"], s["metric"]
        sid = f"slice:{sname}/{mid}"
        a = per_item(pr, mid, slice_name=sname)
        b = per_item(base, mid, slice_name=sname)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        else:
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap(
                        [a[k] for k in keys],
                        [b[k] for k in keys],
                        n_resamples=bs.get("n_resamples", 1000),
                        rng=bs.get("rng", 2027),
                        confidence=bs.get("confidence", 0.95),
                    )
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
