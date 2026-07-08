#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
BPLL Tagging + Aggregation + Trajectory Pipeline
=================================================
The "machine" for analysis step 7 (METHODS.md §3, §5, §7):
  input : cleaned main sample + audited seed lexicon
  step 1: tag every post with L1/L2 categories (with disambiguation rules)
  step 2: aggregate category shares per brand x period, Wilson 95% CI
  step 3: plot share trajectories T0 -> T1 -> T2

SEALING PROTOCOL (METHODS.md §7):
  - default refuses to run on real data; requires one of:
        --placebo shuffle    (brand labels shuffled, seed=42)
        --placebo t0-only    (only T0 rows fed; no before/after contrast exists)
        --unseal             (real run; only after brief freeze + lexicon validation)
  - every run appends to run_log.jsonl (timestamp, mode, input hash).

Usage:
    python tag_and_aggregate.py --data cleaned/main_sample.csv \
        --seeds audit_out/seed_words_v0_audited.csv --outdir pipeline_out \
        --placebo shuffle

Command:
    placebo shuffle:
        python .\scripts\tag_and_aggregate.py --data .\input\cleaned_weibo\main_sample.csv --seeds .\lexicon\audit\seed_words_v0_audited.csv --outdir .\report\shuffle --placebo shuffle
    placebo t0-only:
        python .\scripts\tag_and_aggregate.py --data .\input\cleaned_weibo\main_sample.csv --seeds .\lexicon\audit\seed_words_v0_audited.csv --outdir .\report\t0only --placebo t0-only
    unseal:
        python .\scripts\tag_and_aggregate.py --data .\input\cleaned_weibo\main_sample.csv --seeds .\lexicon\audit\seed_words_v0_audited.csv --outdir .\report\unseal --unseal
"""

import argparse
import datetime
import hashlib
import json
import math
import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Disambiguation rules (executable form of METHODS.md §5)
# Each rule: word -> (default_assignment or None, [(context_regex, override_assignment)])
# Assignment is (layer, category) or None (= not counted).
# ---------------------------------------------------------------------------
CRISIS_CTX = r"核|辐射|排海|日货|日系|清单"
DISAMBIG = {
    "避雷":  (("L1", "功效型"), [(CRISIS_CTX, ("L2", "安全恐慌"))]),
    "踩雷":  (("L1", "功效型"), [(CRISIS_CTX, ("L2", "安全恐慌"))]),
    "烂脸":  (("L1", "功效型"), [(r"(还买|谁买|活该|应该).{0,20}(日|货)|((日|货).{0,20}(还买|谁买|活该|应该))",
                                  ("L2", "立场抵制"))]),
    "囤货":  ((None, None), [(r"批次|生产日期|核", ("L2", "安全恐慌"))]),
    "焦虑":  (("L2", "安全恐慌"), [(r"别.{0,6}焦虑|不要.{0,6}焦虑|没必要|制造焦虑", ("L2", "理性辩护"))]),
    "检测":  (("L2", "理性辩护"), [(r"检测仪|自己测|买.{0,8}测", ("L2", "安全恐慌"))]),
    "本子":  ((None, None), [(r"日本|日货|抵制", ("L2", "立场抵制"))]),
    "随便":  ((None, None), [(r"辐射|核|反正|摆烂", ("L2", "摆烂虚无"))]),
    "无所谓": ((None, None), [(r"辐射|核|反正|摆烂", ("L2", "摆烂虚无"))]),
}


def build_lexicon(seeds_path):
    """word -> (layer, category); disambiguated words handled separately."""
    seeds = pd.read_csv(seeds_path, encoding="utf-8-sig")
    lex = {}
    for _, r in seeds.iterrows():
        w = str(r["word"]).strip()
        if w in DISAMBIG:
            continue
        lex[w] = (r["layer"], r["category"])
    return lex


def tag_text(text, lex):
    """Return set of (layer, category) tags for one text."""
    tags = set()
    for w, assign in lex.items():
        if w in text:
            tags.add(assign)
    for w, (default, overrides) in DISAMBIG.items():
        if w in text:
            assigned = default if default[0] is not None else None
            for ctx_re, override in overrides:
                if re.search(ctx_re, text):
                    assigned = override
                    break
            if assigned is not None:
                tags.add(assigned)
    return tags


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def log_run(outdir, mode, data_path, n_rows):
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "input": str(data_path),
        "input_md5": hashlib.md5(Path(data_path).read_bytes()).hexdigest()[:12],
        "n_rows": int(n_rows),
    }
    with open(Path(outdir) / "run_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run(data_path, seeds_path, outdir, mode):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(data_path, encoding="utf-8-sig")
    text_col = "text_norm" if "text_norm" in df.columns else "text_content"

    # ---- sealing modes ------------------------------------------------------
    if mode == "placebo-shuffle":
        df["brand_category"] = (df["brand_category"]
                                .sample(frac=1.0, random_state=42)
                                .reset_index(drop=True))
        prefix = "PLACEBO_SHUFFLE_"
    elif mode == "placebo-t0":
        df = df[df["time_period"] == "T0"].copy()
        prefix = "PLACEBO_T0ONLY_"
    elif mode == "UNSEALED":
        prefix = ""
    else:
        raise ValueError(mode)

    log_run(outdir, mode, data_path, len(df))

    # ---- step 1: tagging -----------------------------------------------------
    lex = build_lexicon(seeds_path)
    all_cats = sorted(set(lex.values()) | {a for d, o in DISAMBIG.values()
                                           for a in ([d] + [x[1] for x in o])
                                           if a[0] is not None})
    tag_sets = df[text_col].astype(str).map(lambda t: tag_text(t, lex))
    for layer, cat in all_cats:
        col = f"tag_{layer}_{cat}"
        df[col] = tag_sets.map(lambda s, lc=(layer, cat): int(lc in s))

    df.to_csv(outdir / f"{prefix}tagged.csv", index=False, encoding="utf-8-sig")

    # ---- step 2: aggregation -------------------------------------------------
    rows = []
    for (brand, period), g in df.groupby(["brand_category", "time_period"]):
        n = len(g)
        for layer, cat in all_cats:
            k = int(g[f"tag_{layer}_{cat}"].sum())
            p, lo, hi = wilson_ci(k, n)
            rows.append({"brand": brand, "period": period, "layer": layer,
                         "category": cat, "n": n, "k": k,
                         "share": round(p, 4), "ci_lo": round(lo, 4),
                         "ci_hi": round(hi, 4)})
    agg = pd.DataFrame(rows)
    agg.to_csv(outdir / f"{prefix}category_shares.csv", index=False, encoding="utf-8-sig")

    # ---- step 3: trajectory plot ----------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        cjk = None
        for f in font_manager.fontManager.ttflist:
            if ("Noto Sans CJK" in f.name or "WenQuanYi" in f.name
                or "Microsoft YaHei" in f.name or "SimHei" in f.name or "SimSun" in f.name):
                cjk = f.name
                break
        if cjk:
            plt.rcParams["font.family"] = cjk

        focus = [("L2", "立场抵制"), ("L2", "安全恐慌"),
                 ("L2", "理性辩护"), ("L2", "替代转投")]
        brands = sorted(df["brand_category"].unique())
        periods = ["T0", "T1", "T2"]
        fig, axes = plt.subplots(1, len(focus), figsize=(5 * len(focus), 4),
                                 sharey=True)
        for ax, (layer, cat) in zip(axes, focus):
            for b in brands:
                sub = agg[(agg["brand"] == b) & (agg["layer"] == layer)
                          & (agg["category"] == cat)].set_index("period")
                y = [sub.loc[p, "share"] if p in sub.index else None for p in periods]
                ax.plot(periods, y, marker="o", label=b)
            ax.set_title(f"{cat}" + (" (PLACEBO)" if prefix else ""))
            ax.set_ylabel("share of posts")
        axes[0].legend(fontsize=8)
        fig.suptitle(f"{prefix}category share trajectories")
        fig.tight_layout()
        fig.savefig(outdir / f"{prefix}trajectories.png", dpi=150)
    except Exception as e:  # plotting must never block tagging output
        print(f"[warn] plot skipped: {e}")

    print(json.dumps({"mode": mode, "rows_processed": len(df),
                      "categories": len(all_cats),
                      "output_prefix": prefix or "(REAL RUN)"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--outdir", default="pipeline_out")
    ap.add_argument("--placebo", choices=["shuffle", "t0-only"], default=None)
    ap.add_argument("--unseal", action="store_true",
                    help="Run on real data. ONLY after brief freeze + lexicon "
                         "validation (METHODS.md sealing protocol).")
    a = ap.parse_args()
    if a.unseal and a.placebo:
        raise SystemExit("Choose either --unseal or --placebo, not both.")
    if not a.unseal and not a.placebo:
        raise SystemExit("SEALED: specify --placebo {shuffle,t0-only} for development, "
                         "or --unseal for the real run (requires freeze).")
    mode = "UNSEALED" if a.unseal else ("placebo-shuffle" if a.placebo == "shuffle"
                                        else "placebo-t0")
    run(a.data, a.seeds, a.outdir, mode)
