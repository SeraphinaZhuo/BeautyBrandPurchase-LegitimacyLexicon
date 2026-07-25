# Data Quality Report — Weibo corpus

输入行数：**31677**

| 规则 | 移出行数 | 去向文件 |
|---|---|---|
| R1 完全重复 | 23557 | archive_duplicates.csv |
| R6 品牌词误命中(花王) | 5 | archive_offtopic.csv |
| R2 广告/带货/抽奖 | 462 | archive_promo.csv |
| R3 无信息内容 | 223 | archive_lowinfo.csv |
| R8-R12 残余噪音 | 1276 | archive_residual_noise.csv |
| R4 机构账号分流 | 784 | sample_institutional.csv |

**主样本（普通用户）：5370 条**

## 主样本 品牌 × 时段

| brand_category   |   T0 |   T1 |   T2 |
|:-----------------|-----:|-----:|-----:|
| SK-II            |  172 |  315 |  193 |
| 珀莱雅              |  110 |  288 |  112 |
| 花王               |  123 |  380 |  206 |
| 蜂花               |  115 |  525 |  233 |
| 资生堂              |  586 | 1267 |  745 |

## 主样本 content_type

| content_type   |   count |
|:---------------|--------:|
| 热门评论           |    3525 |
| 主贴正文           |    1845 |

## 分析用旗标

- crisis_flag=1（含核污水词簇）占比：9.8%
- 蜂花样本中 huaxizi_flag=1（花西子事件混杂）：66 条

## 各品牌广告占比（R2移出量 /（R2+主样本））

- SK-II: 3.7%
- 珀莱雅: 26.0%
- 花王: 12.1%
- 蜂花: 6.0%
- 资生堂: 3.8%

---
*本报告由 clean_weibo.py 自动生成。所有排除均为移动而非删除，可全量复原。*