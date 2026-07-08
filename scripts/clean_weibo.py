#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BPLL Data Cleaning Script (Weibo corpus)
=========================================
Implements cleaning rules R1-R7 derived from Research Brief §7 and Codebook v1 §4.

Design principles:
  - MOVE, never DELETE: every excluded row goes to a named archive file with an
    `exclusion_rule` column, so the full pipeline is reversible and auditable.
  - Deterministic: same input -> same output. No randomness, no external calls.
  - Ad detection is heuristic-scored, not keyword-only: a post is flagged as
    promotional if it accumulates enough weighted signals (price patterns,
    giveaway language, call-to-action verbs, template duplication), so ads
    that avoid any single obvious keyword still get caught.

Usage:
    python clean_weibo.py --input weibo_beauty_crisis_data.csv --outdir cleaned

Command:
    python .\scripts\clean_weibo.py --input .\input\weibo_beauty_crisis_data.csv --outdir reports/cleaned_weibo

Outputs (all CSV, UTF-8):
    main_sample.csv           <- analysis-ready ordinary-user sample
    sample_institutional.csv  <- blue-V / brand-official accounts (R4)
    archive_duplicates.csv    <- exact duplicates beyond first copy (R1)
    archive_promo.csv         <- promotional / giveaway / affiliate content (R2)
    archive_lowinfo.csv       <- no-information posts (R3)
    archive_offtopic.csv      <- brand-keyword false positives (R6)
    dq_report.md              <- auto-generated Data Quality Report
    dq_stats.json             <- machine-readable stats for reproducibility diff
"""

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# 0. Text normalization
# ---------------------------------------------------------------------------

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\uFE0F"
    "]+"
)
XHS_EMOTE_RE = re.compile(r"\[[^\[\]]{1,8}R?\]")          # [哭惹R] [微笑R] ...
HASHTAG_RE = re.compile(r"#[^#]{1,40}#")                   # #topic#
MENTION_RE = re.compile(r"@[\w\u4e00-\u9fff\-·]{1,30}")
URL_TOKEN_RE = re.compile(r"网页链接|https?://\S+")


def normalize_text(raw: str) -> str:
    """HTML-unescape and collapse whitespace. Keeps emojis/hashtags (needed for
    sentiment & topic later); this is canonical form for duplicate detection."""
    if not isinstance(raw, str):
        return ""
    t = html.unescape(raw)              # &gt; -> >, &amp; -> &
    t = re.sub(r"\s+", " ", t).strip()
    return t


def effective_length(text: str) -> int:
    """Length after stripping emojis, XHS emotes, hashtags, mentions, URLs and
    punctuation. Approximates 'how much actual message is here'."""
    t = URL_TOKEN_RE.sub("", text)
    t = HASHTAG_RE.sub("", t)
    t = MENTION_RE.sub("", t)
    t = XHS_EMOTE_RE.sub("", t)
    t = EMOJI_RE.sub("", t)
    t = re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE)
    return len(t)


# ---------------------------------------------------------------------------
# R2. Promotional-content scoring
# ---------------------------------------------------------------------------
# STRONG signals: one hit is近乎确凿 (affiliate/giveaway mechanics, coupon flows).
# WEAK signals: common in ads but also in organic talk; need >=2 distinct hits
# (or 1 weak hit + template duplication) to classify as promo.
# Rationale: organic posts DO mention prices or 双十一; only the co-occurrence
# of several sales mechanics marks a post as marketing.

STRONG_PROMO = [
    r"领券", r"凑单", r"拼团价?", r"抽奖详情", r"抽奖平台",
    r"评论反馈.{0,12}(抽|揪)", r"(抽|揪)\d+个?(宝|姐妹|人)",
    r"平分\d+", r"打钱|打款|大洋", r"到手价", r"专享价", r"补贴后?到手",
    r"网页链接", r"私我", r"微店", r"下单链接", r"转发过百",
]
WEAK_PROMO = [
    r"到手\d+", r"【?\d{2,4}(💰|元|块)?】", r"💰\s*\d+", r"史低", r"好价",
    r"速度上车", r"抢完(就|即)?(下架|没|不补)", r"限量\d+件", r"库存",
    r"买一送一", r"第二件半价", r"直播间", r"旗舰店", r"官方正品",
    r"回购榜|销量榜", r"包邮", r"现货", r"薅", r"闭眼(入|冲)",
    r"双十一|双11|618|大促|抢先购", r"点赞?👍", r"福利", r"折扣|优惠",
    r"同款", r"安利给你们", r"囤(他|它|起来)",
]
STRONG_PROMO_RE = [re.compile(p) for p in STRONG_PROMO]
WEAK_PROMO_RE = [re.compile(p) for p in WEAK_PROMO]


def promo_score(text: str):
    """Return (strong_hits, weak_hits) counts of DISTINCT patterns matched."""
    s = sum(1 for p in STRONG_PROMO_RE if p.search(text))
    w = sum(1 for p in WEAK_PROMO_RE if p.search(text))
    return s, w


# ---------------------------------------------------------------------------
# R3. Low-information content
# ---------------------------------------------------------------------------
# CAUTION: very short comments can be real data ("不买", "不敢用", "抵制").
# Therefore we do NOT use a naive length cutoff. A row is low-info only if:
#   (a) its effective length is 0-1 characters, OR
#   (b) the whole message matches a known noise pattern (repost stubs, filler).
# "不买" (eff. length 2) survives; "转发微博" does not.

NOISE_EXACT = {
    "转发微博", "关注", "来了", "图片评论", "码住", "马住", "mark", "Mark",
    "好", "赞", "顶", "路过", "沙发", "打卡", "学习", "收藏", "蹲", "dd", "DD",
    "转发", "支持", "来啦", "看看", "冲",
}
NOISE_RE = re.compile(r"^(哈{2,}|嗯+|噢+|哦+|啊+|\d{2,4}|[.。!！?？~～]+|666+|233+)$")


def is_lowinfo(text_norm: str) -> bool:
    core = URL_TOKEN_RE.sub("", text_norm).strip()
    if core in NOISE_EXACT:
        return True
    if NOISE_RE.match(core):
        return True
    if effective_length(text_norm) <= 1:
        return True
    return False


# ---------------------------------------------------------------------------
# R6. Brand-keyword false positives
# ---------------------------------------------------------------------------
# "花王" collides with 牡丹=花中之王 (Dream of the Red Chamber, painters'
# sobriquets, fandom posts). Rows for brand 花王 that contain flower-king /
# fine-arts context and NO daily-chemicals context are moved to offtopic.

KAO_OFFTOPIC_RE = re.compile(
    r"牡丹|芍药|花中之王|花相|工笔|书法|美术师|画家|昆曲|红楼|诗词|水墨"
)
KAO_PRODUCT_RE = re.compile(
    r"卫生巾|乐而雅|洗衣|洗发|沐浴|洗洁|清洁|蒸汽眼罩|眼罩|安睡裤|姨妈|"
    r"碧柔|洁霸|洁厕|花王的|花王家"
)


def is_kao_offtopic(brand: str, text: str) -> bool:
    if brand != "花王":
        return False
    return bool(KAO_OFFTOPIC_RE.search(text)) and not KAO_PRODUCT_RE.search(text)


# ---------------------------------------------------------------------------
# R7. Analysis flags (added as columns; rows are NOT removed)
# ---------------------------------------------------------------------------

CRISIS_RE = re.compile(r"核污水|核废水|核污染|排海|核辐射|辐射|福岛")
HUAXIZI_RE = re.compile(r"花西子|李佳琦|佳琦|眉笔|79元|79块")
GUOCHAO_RE = re.compile(r"国货|国产|国牌")


# ---------------------------------------------------------------------------
# Template duplication (supports R2)
# ---------------------------------------------------------------------------

def template_prefixes(texts: pd.Series, prefix_len: int = 30, min_count: int = 3):
    """Prefixes (post-normalization) shared by >= min_count distinct rows.
    Marketing copy is pasted across many accounts with small tail edits, so a
    long identical prefix repeated across rows is strong template evidence."""
    prefixes = texts.str.slice(0, prefix_len)
    counts = prefixes.value_counts()
    return set(counts[counts >= min_count].index) - {""}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(input_path: Path, outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    n0 = len(df)

    df["text_norm"] = df["text_content"].map(normalize_text)

    # ---- R1: exact duplicates -------------------------------------------
    dup_mask = df.duplicated(subset=["post_id", "text_norm"], keep="first")
    archive_dup = df[dup_mask].copy()
    archive_dup["exclusion_rule"] = "R1_duplicate"
    df = df[~dup_mask].copy()

    # ---- R6: brand-keyword false positives (before promo, they are neither ads
    # nor data) -------------------------------------------------------------
    off_mask = df.apply(lambda r: is_kao_offtopic(str(r["brand_category"]), r["text_norm"]), axis=1)
    archive_off = df[off_mask].copy()
    archive_off["exclusion_rule"] = "R6_brand_false_positive"
    df = df[~off_mask].copy()

    # ---- R4: account split (BEFORE R2/R3) ---------------------------------
    # Rationale: blue-V media posts (e.g. "双11日系化妆品遇冷" news) share surface
    # features with ads (双11, sales figures) and would be wrongly killed by R2.
    # Institutional content is preserved whole in its own sample; R2/R3 apply
    # to ordinary users only.
    inst_mask = df["user_type"].isin(["蓝V认证账号", "品牌官方"])
    sample_inst = df[inst_mask].copy()
    df = df[~inst_mask].copy()

    # ---- R2: promotional content (ordinary users only) --------------------
    scores = df["text_norm"].map(promo_score)
    df["_strong"] = [s for s, _ in scores]
    df["_weak"] = [w for _, w in scores]
    tpl = template_prefixes(df["text_norm"])
    df["_template"] = df["text_norm"].str.slice(0, 30).isin(tpl)

    promo_mask = (
        (df["_strong"] >= 1)
        | (df["_weak"] >= 2)
        | ((df["_weak"] >= 1) & df["_template"])
    )
    archive_promo = df[promo_mask].copy()
    archive_promo["exclusion_rule"] = "R2_promotional"
    df = df[~promo_mask].copy()

    # ---- R3: low-information --------------------------------------------
    low_mask = df["text_norm"].map(is_lowinfo)
    archive_low = df[low_mask].copy()
    archive_low["exclusion_rule"] = "R3_low_information"
    df = df[~low_mask].copy()

    # ---- R7: flags --------------------------------------------------------
    for frame in (df, sample_inst):
        frame["crisis_flag"] = frame["text_norm"].str.contains(CRISIS_RE).astype(int)
        frame["huaxizi_flag"] = (
            (frame["brand_category"] == "蜂花")
            & frame["text_norm"].str.contains(HUAXIZI_RE)
        ).astype(int)
        frame["guohuo_flag"] = frame["text_norm"].str.contains(GUOCHAO_RE).astype(int)

    df = df.drop(columns=["_strong", "_weak", "_template"])
    for a in (archive_promo,):
        a.drop(columns=["_strong", "_weak", "_template"], inplace=True, errors="ignore")

    # ---- write outputs ----------------------------------------------------
    df.to_csv(outdir / "main_sample.csv", index=False, encoding="utf-8-sig")
    sample_inst.drop(columns=["_strong", "_weak", "_template"], errors="ignore").to_csv(
    outdir / "sample_institutional.csv", index=False, encoding="utf-8-sig")
    archive_dup.to_csv(outdir / "archive_duplicates.csv", index=False, encoding="utf-8-sig")
    archive_promo.to_csv(outdir / "archive_promo.csv", index=False, encoding="utf-8-sig")
    archive_low.to_csv(outdir / "archive_lowinfo.csv", index=False, encoding="utf-8-sig")
    archive_off.to_csv(outdir / "archive_offtopic.csv", index=False, encoding="utf-8-sig")

    # ---- stats -------------------------------------------------------------
    def brand_period(frame):
        if len(frame) == 0:
            return {}
        ct = pd.crosstab(frame["brand_category"], frame["time_period"])
        return {b: ct.loc[b].to_dict() for b in ct.index}

    stats = {
        "input_rows": int(n0),
        "R1_duplicates_removed": int(len(archive_dup)),
        "R6_offtopic_removed": int(len(archive_off)),
        "R2_promo_removed": int(len(archive_promo)),
        "R3_lowinfo_removed": int(len(archive_low)),
        "R4_institutional_split": int(len(sample_inst)),
        "main_sample_rows": int(len(df)),
        "AUDIT_promo_rows_containing_crisis_words": int(
            archive_promo["text_norm"].str.contains(CRISIS_RE).sum()),
        "main_sample_brand_x_period": brand_period(df),
        "main_sample_content_type": df["content_type"].value_counts().to_dict(),
        "crisis_flag_share": round(float(df["crisis_flag"].mean()), 4),
        "huaxizi_flag_count_fenghua": int(df["huaxizi_flag"].sum()),
        "promo_share_by_brand": {
            b: round(float((archive_promo["brand_category"] == b).sum()
                     / max(1, ((archive_promo["brand_category"] == b).sum()
                     + (df["brand_category"] == b).sum()))), 4)
            for b in sorted(set(archive_promo["brand_category"]) | set(df["brand_category"]))
        },
    }
    with open(outdir / "dq_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # ---- markdown report ----------------------------------------------------
    report = ["# Data Quality Report — Weibo corpus\n"]
    report.append(f"输入行数：**{n0}**\n")
    report.append("| 规则 | 移出行数 | 去向文件 |")
    report.append("|---|---|---|")
    report.append(f"| R1 完全重复 | {len(archive_dup)} | archive_duplicates.csv |")
    report.append(f"| R6 品牌词误命中(花王) | {len(archive_off)} | archive_offtopic.csv |")
    report.append(f"| R2 广告/带货/抽奖 | {len(archive_promo)} | archive_promo.csv |")
    report.append(f"| R3 无信息内容 | {len(archive_low)} | archive_lowinfo.csv |")
    report.append(f"| R4 机构账号分流 | {len(sample_inst)} | sample_institutional.csv |")
    report.append(f"\n**主样本（普通用户）：{len(df)} 条**\n")
    report.append("## 主样本 品牌 × 时段\n")
    ct = pd.crosstab(df["brand_category"], df["time_period"])
    report.append(ct.to_markdown())
    report.append("\n## 主样本 content_type\n")
    report.append(df["content_type"].value_counts().to_frame().to_markdown())
    report.append("\n## 分析用旗标\n")
    report.append(f"- crisis_flag=1（含核污水词簇）占比：{df['crisis_flag'].mean():.1%}")
    report.append(f"- 蜂花样本中 huaxizi_flag=1（花西子事件混杂）：{int(df['huaxizi_flag'].sum())} 条")
    report.append("\n## 各品牌广告占比（R2移出量 /（R2+主样本））\n")
    for b, v in stats["promo_share_by_brand"].items():
        report.append(f"- {b}: {v:.1%}")
    report.append("\n---\n*本报告由 clean_weibo.py 自动生成。所有排除均为移动而非删除，可全量复原。*")
    (outdir / "dq_report.md").write_text("\n".join(report), encoding="utf-8")

    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--outdir", default=Path("cleaned"), type=Path)
    args = ap.parse_args()
    s = run(args.input, args.outdir)
    print(json.dumps(s, ensure_ascii=False, indent=2))
