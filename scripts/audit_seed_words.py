#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
BPLL Seed Word Audit + Coverage Diagnostic
==========================================
Two directions of the same check (METHODS.md §4, §6):
  1. AUDIT  : for every seed word, how often does it occur in the corpus?
              -> flags corpus_absent (0 hits) / sparse (1-4 hits) as prior_driven
  2. COVERAGE: for every document, is it hit by at least one seed word?
              -> share of documents carrying >=1 L1 tag / >=1 L2 tag

Usage:
    python audit_seed_words.py \
        --seeds seed_words_v0.csv \
        --weibo main_sample.csv \
        --xhs-notes xhs_notes_data.xlsx \
        --xhs-comments xhs_comments_data.xlsx \
        --outdir audit_dir

Command:
    python .\scripts\audit_seed_words.py --seeds .\lexicon\seed_words_v0.csv --weibo .\reports\cleaned_weibo\main_sample.csv --xhs-notes .\input\xhs_notes_data.xlsx --xhs-comments .\input\xhs_comments_data.xlsx --outdir .\reports\audited

Outputs:
    seed_words_v0_audited.csv  <- original columns + hit counts + flags
    audit_report.md            <- human-readable summary
    audit_stats.json           <- machine-readable, for two-runner diff
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

SPARSE_THRESHOLD = 5  # hits < 5 -> "sparse" (METHODS.md §4)


def load_corpus(weibo_path, notes_path, comments_path):
    """Return a single DataFrame with columns: text, source."""
    frames = []
    wb = pd.read_csv(weibo_path, encoding="utf-8-sig")
    text_col = "text_norm" if "text_norm" in wb.columns else "text_content"
    frames.append(pd.DataFrame({"text": wb[text_col].astype(str), "source": "weibo_main"}))
    if notes_path:
        n = pd.read_excel(notes_path)
        frames.append(pd.DataFrame({"text": n["具体文本"].astype(str), "source": "xhs_notes"}))
    if comments_path:
        c = pd.read_excel(comments_path)
        frames.append(pd.DataFrame({"text": c["具体文本"].astype(str), "source": "xhs_comments"}))
    return pd.concat(frames, ignore_index=True)


def run(seeds_path, weibo_path, notes_path, comments_path, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    seeds = pd.read_csv(seeds_path, encoding="utf-8-sig")
    corpus = load_corpus(weibo_path, notes_path, comments_path)
    texts = corpus["text"].tolist()
    sources = corpus["source"].tolist()

    # ---- 1. AUDIT: per-word hit counts (document frequency, substring match)
    rows = []
    for _, s in seeds.iterrows():
        w = str(s["word"]).strip()
        hits_by_src = {"weibo_main": 0, "xhs_notes": 0, "xhs_comments": 0}
        for t, src in zip(texts, sources):
            if w in t:
                hits_by_src[src] += 1
        total = sum(hits_by_src.values())
        flag = ""
        if total == 0:
            flag = "corpus_absent"
        elif total < SPARSE_THRESHOLD:
            flag = "sparse"
        rows.append({
            **s.to_dict(),
            "hits_weibo": hits_by_src["weibo_main"],
            "hits_xhs_notes": hits_by_src["xhs_notes"],
            "hits_xhs_comments": hits_by_src["xhs_comments"],
            "hits_total": total,
            "prior_driven": flag,   # empty = corpus-evidenced
        })
    audited = pd.DataFrame(rows)
    audited.to_csv(outdir / "seed_words_v0_audited.csv", index=False, encoding="utf-8-sig")

    # ---- 2. COVERAGE: per-document, >=1 hit in each layer -------------------
    l1_words = audited[audited["layer"] == "L1"]["word"].astype(str).tolist()
    l2_words = audited[audited["layer"] == "L2"]["word"].astype(str).tolist()
    l1_re = re.compile("|".join(map(re.escape, l1_words)))
    l2_re = re.compile("|".join(map(re.escape, l2_words)))

    cov = {}
    for src in ("weibo_main", "xhs_notes", "xhs_comments"):
        sub = [t for t, s in zip(texts, sources) if s == src]
        if not sub:
            continue
        l1_hit = sum(1 for t in sub if l1_re.search(t))
        l2_hit = sum(1 for t in sub if l2_re.search(t))
        any_hit = sum(1 for t in sub if l1_re.search(t) or l2_re.search(t))
        cov[src] = {
            "n_docs": len(sub),
            "l1_coverage": round(l1_hit / len(sub), 4),
            "l2_coverage": round(l2_hit / len(sub), 4),
            "any_coverage": round(any_hit / len(sub), 4),
        }

    # ---- category-level hit mass -------------------------------------------
    cat = (audited.groupby(["layer", "category"])
           .agg(n_words=("word", "count"),
                total_hits=("hits_total", "sum"),
                n_prior_driven=("prior_driven", lambda x: int((x != "").sum())))
           .reset_index())

    stats = {
        "n_seed_words": int(len(audited)),
        "n_corpus_absent": int((audited["prior_driven"] == "corpus_absent").sum()),
        "n_sparse": int((audited["prior_driven"] == "sparse").sum()),
        "coverage": cov,
        "per_category": cat.to_dict(orient="records"),
    }
    with open(outdir / "audit_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # ---- markdown report -----------------------------------------------------
    rep = ["# 种子词审计 + 覆盖率诊断报告\n"]
    rep.append(f"种子词总数：{stats['n_seed_words']}；"
               f"语料零出现（corpus_absent）：{stats['n_corpus_absent']}；"
               f"稀疏（sparse, <{SPARSE_THRESHOLD}次）：{stats['n_sparse']}\n")
    rep.append("## 被标记为 prior_driven 的词\n")
    pd_words = audited[audited["prior_driven"] != ""]
    for _, r in pd_words.iterrows():
        rep.append(f"- **{r['word']}** ({r['layer']}/{r['category']}) — "
                   f"总命中 {r['hits_total']} 次 → {r['prior_driven']}")
    rep.append("\n## 覆盖率（文档层面，至少命中一个种子词）\n")
    rep.append("| 语料 | 文档数 | L1覆盖 | L2覆盖 | 任一覆盖 |")
    rep.append("|---|---|---|---|---|")
    for src, v in cov.items():
        rep.append(f"| {src} | {v['n_docs']} | {v['l1_coverage']:.1%} | "
                   f"{v['l2_coverage']:.1%} | {v['any_coverage']:.1%} |")
    rep.append("\n## 各类别命中质量\n")
    rep.append("| 层 | 类别 | 词数 | 总命中 | prior_driven词数 |")
    rep.append("|---|---|---|---|---|")
    for r in stats["per_category"]:
        rep.append(f"| {r['layer']} | {r['category']} | {r['n_words']} | "
                   f"{r['total_hits']} | {r['n_prior_driven']} |")
    rep.append("\n---\n*由 audit_seed_words.py 自动生成。prior_driven 词保留于词表并公开标记"
               "（METHODS.md §4）。*")
    (outdir / "audit_report.md").write_text("\n".join(rep), encoding="utf-8")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--weibo", required=True)
    ap.add_argument("--xhs-notes", default=None)
    ap.add_argument("--xhs-comments", default=None)
    ap.add_argument("--outdir", default="audit_out")
    a = ap.parse_args()
    s = run(a.seeds, a.weibo, a.xhs_notes, a.xhs_comments, a.outdir)
    print(json.dumps({k: v for k, v in s.items() if k != "per_category"},
                     ensure_ascii=False, indent=2))
