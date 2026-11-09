#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
寓言文本自检脚本 lint_fable.py

用法:
    python lint_fable.py 输出.md
    python lint_fable.py 输出.md --json
    python lint_fable.py 输出.md --strict     # 有 WARN 也算失败

检测项:
    1. 字数（中文正文 ≤ 1000 字为佳）
    2. 角色数（≤ 3 为佳，2 最佳）
    3. 意象黑名单
    4. 过度文艺化地名
    5. 结构套路（智者点拨 / 异象顿悟 / 孩童点醒 / 师徒辩难 / 临终遗言）
    6. 角色黑名单（钟表匠、隐士……）
    7. 开头黑名单（从前有个地方……）
    8. 概念术语泄漏（story 段落内出现概念名/术语）
    9. 替身意象提示（想用黑名单意象时的替代方案）

退出码: 0 = 通过, 1 = 有 ERROR
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------- 黑名单

IMAGE_BAN = [
    "钟", "河流", "镜子", "迷宫", "织布机", "地图", "灯塔", "棋盘",
    "回声", "影子", "沙漏", "风", "蜡烛", "种子", "桥", "星辰",
    "蝴蝶", "蛛网",
]

# 需要更精确匹配的（避免误伤，如"钟表"也算、"风声"也算）
IMAGE_BAN_STRICT = {
    "钟": ["时钟", "钟表", "钟楼", "挂钟", "闹钟", "秒针", "分针", "时针", "钟声"],
    "风": ["风筝", "风景", "风险", "风车", "风口", "风味"],
    "桥": ["桥梁", "桥墩", "天桥"],
    "种子": ["种子选手", "种子轮"],
}

PLACE_BAN = [
    "回声城", "记忆之村", "遗忘之海", "寂静谷", "回音谷", "梦之谷",
    "时光镇", "遗忘之地", "静谧谷", "回声镇", "空城", "幽谷",
]

# 地名启发式
PLACE_CALL_RE = re.compile(r"(?:叫|名叫|叫做)([\u4e00-\u9fa5]{1,6}?)(?:的(?:地方|村子|镇子|城|镇|村|谷))")
PLACE_SUFFIX_RE = re.compile(r"([\u4e00-\u9fa5]{2})(镇|村|谷|城|川|湾|岛|州)")
PLACE_ORDINARY = {
    "小镇", "村子", "城市", "山谷", "海边", "河湾", "县城", "省城", "古城",
    "乡镇", "山村", "渔村", "城区", "郊区", "附近", "周边", "整个", "这个",
    "那个", "镇上", "村里", "城里", "山下", "海边", "河川", "平川",
}

STRUCT_BAN = [
    ("智者点拨", ["智者", "老人", "长者", "贤者", "先知", "隐士", "老者", "先生您", "请教", "求教", "指教"]),
    ("异象顿悟", ["异象", "奇观", "顿悟", "幡然醒悟", "恍然大悟", "如梦初醒", "突然明白"]),
    ("孩童点醒", ["小孩", "孩子", "孩童", "童声", "奶声", "孩童说", "孩子说"]),
    ("师徒辩难", ["师徒", "师父", "徒弟", "师父说", "徒儿"]),
    ("临终遗言", ["临终", "遗言", "临死", "弥留", "最后的话", "咽气"]),
]

ROLE_BAN = [
    "钟表匠", "图书管理员", "隐士", "说书人", "老船夫", "酿酒师", "铁匠", "抄经人",
]

OPENING_BAN = [
    "从前有个地方", "从前有一天", "从前有一个人", "很久很久以前", "某天某人",
    "在很远的山里", "在很远的地方", "很久以前", "有一年", "故事发生在",
]

# 开头启发式（正则）
OPENING_RE = [
    (r"^\s*从前", "从前…"),
    (r"^\s*很久(?:很久)?(?:以前|之前|前)", "很久以前…"),
    (r"^\s*有一(?:天|年|回|次)", "有一天/有一年…"),
    (r"^\s*某(?:天|日|年|个)", "某天/某个…"),
    (r"^\s*在(?:很远|遥远|很久|某个|一片)", "在很远/某个…"),
    (r"^\s*故事(?:发生|开始)", "故事发生在…"),
    (r"^\s*相?传(?:在|有)", "相传…"),
]

# 术语泄漏：概念相关词汇（可按需扩充）。这些词一旦出现在正文段落即视为术语泄漏。
TERM_BAN = [
    "边际效用", "效用递减", "沉没成本", "机会成本", "复利", "熵增", "熵",
    "网络效应", "正反馈", "负反馈", "博彩", "均值回归", "边际成本",
    "激励相容", "信息不对称", "交易成本", "路径依赖", "规模经济", "范围经济",
    "边际收益", "边际", "效用", "成本", "收益", "回报率", "复利效应",
]

# 替身意象建议
SUBSTITUTE = {
    "钟": "班次/换班表/打卡记录/保质期",
    "河流": "输送带/分拣轨道/管道内壁",
    "镜子": "工牌上的旧照片/交接本上的签名",
    "迷宫": "库房动线/货架空位",
    "织布机": "流水线工位/装订线",
    "地图": "配送区域划分表",
    "灯塔": "值班室的白炽灯/手电筒",
    "棋盘": "分拣台上的岔道",
    "回声": "二手转述的口头通知",
    "影子": "换下的工服/登记表上的旧签名",
    "沙漏": "交接班倒计时/工时表",
    "风": "车间气流/冷气口",
    "蜡烛": "夜班灯/值班台小灯",
    "种子": "刚入库的一批货/新员工",
    "桥": "跨班次的交接单",
    "星辰": "排班表上的班次编号",
    "蝴蝶": "折叠标签的纸样",
    "蛛网": "交接群里的消息记录",
}

# ---------------------------------------------------------------- 解析

FRONT_RE = re.compile(r"<!--\s*fable-lint(.*?)-->", re.S)
FIELD_RE = re.compile(r"^\s*(\w+)\s*[:：]\s*(.+?)\s*$", re.M)


PART_RE = re.compile(r"^第\s*([一二三123])\s*部分")


def _part_marker(line):
    """返回 1/2/3 表示该行是第几部分的标记行，否则 None。"""
    s = line.strip().lstrip("#").strip()
    m = PART_RE.match(s)
    if not m:
        return None
    ch = m.group(1)
    return {"一": 1, "二": 2, "三": 3, "1": 1, "2": 2, "3": 3}.get(ch)


def split_sections(text):
    """把三段式输出拆成 (正文, 解析, 检验问题)。

    以「第一部分 / 第二部分 / 第三部分」为锚点，锚点缺失时退化为标题切分。
    """
    lines = text.split("\n")
    marks = []  # (行号, 部分号)
    for i, ln in enumerate(lines):
        p = _part_marker(ln)
        if p:
            marks.append((i, p))

    if not marks:
        # 退化：找第一个 markdown 标题
        for i, ln in enumerate(lines):
            if re.match(r"^#{1,6}\s+", ln):
                return "\n".join(lines[:i]), "\n".join(lines[i:]), ""
        return text, "", ""

    p1 = next((i for i, p in marks if p == 1), None)
    p2 = next((i for i, p in marks if p == 2), None)
    p3 = next((i for i, p in marks if p == 3), None)

    if p1 is None:
        p1 = marks[0][0]

    body_end = p2 if p2 is not None else (p3 if p3 is not None else len(lines))
    analysis_end = p3 if p3 is not None else len(lines)

    body = "\n".join(lines[p1 + 1:body_end])
    analysis = "\n".join(lines[body_end:analysis_end]) if p2 is not None else ""
    quiz = "\n".join(lines[analysis_end:]) if p3 is not None else ""
    return body, analysis, quiz


def split_fables(text):
    """一个文件里可能有多则寓言，按「第一部分」出现位置切块。"""
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if _part_marker(ln) == 1]
    if not starts:
        return [(text, None)]
    chunks = []
    for idx, s in enumerate(starts):
        e = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        chunk = "\n".join(lines[s:e])
        # 只带上紧邻本则寓言的注释块（最多回看 30 行），避免误取上一则的元信息
        window = "\n".join(lines[max(0, s - 30):s])
        cm = None
        for m in re.finditer(r"<!--\s*fable-lint(.*?)-->", window, re.S):
            cm = m.group(0)
        if cm:
            chunk = cm + "\n" + chunk
        chunks.append((chunk, s))
    return chunks


def strip_comment(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def cn_count(text):
    """中文字符数 + 英文单词数（粗略算字数）。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z]+", text))
    return cjk + words


def load_meta(text):
    m = FRONT_RE.search(text)
    if not m:
        return {}
    meta = {}
    for k, v in FIELD_RE.findall(m.group(1)):
        meta[k.lower()] = v
    return meta


# ---------------------------------------------------------------- 检查

def check_one(text, path, strict=False):
    """检查单则寓言文本。"""
    meta = load_meta(text)
    body, analysis, quiz = split_sections(strip_comment(text))
    result = {"file": os.path.basename(path), "meta": meta, "issues": []}

    def add(level, code, msg, extra=None):
        item = {"level": level, "code": code, "message": msg}
        if extra:
            item.update(extra)
        result["issues"].append(item)

    # 1. 字数
    n = cn_count(body)
    result["chars"] = n
    if n > 1000:
        add("ERROR", "CHARS", f"正文 {n} 字，超过 1000 字上限（真寓言应更短）")
    elif n > 850:
        add("WARN", "CHARS", f"正文 {n} 字，接近上限，检查是否有铺陈可删")
    elif n < 120:
        add("WARN", "CHARS", f"正文仅 {n} 字，可能撑不起机制")
    else:
        add("OK", "CHARS", f"正文 {n} 字")

    # 2. 角色
    cast = meta.get("cast", "")
    cast_list = [c for c in re.split(r"[,，、/]|\s+", cast) if c]
    result["cast"] = cast_list
    if cast_list:
        if len(cast_list) > 3:
            add("ERROR", "CAST", f"声明角色 {len(cast_list)} 个：{'、'.join(cast_list)}；上限 3 个")
        elif len(cast_list) == 1:
            add("WARN", "CAST", "只有 1 个角色，检查是否有对手戏")
        else:
            add("OK", "CAST", f"角色 {len(cast_list)} 个：{'、'.join(cast_list)}")
    else:
        add("WARN", "CAST", "未声明 cast；自动统计不可靠，请在 <!-- fable-lint --> 里写 cast: 甲,乙")

    # 3. 意象黑名单
    hits = []
    for w in IMAGE_BAN:
        if w in body:
            if w in IMAGE_BAN_STRICT:
                strict_hits = [p for p in IMAGE_BAN_STRICT[w] if p in body]
                if strict_hits:
                    hits.append((w, strict_hits))
            else:
                hits.append((w, [w]))
    if hits:
        for w, matched in hits:
            add("ERROR", "IMAGE_BAN", f"正文出现禁用意象「{w}」（命中：{'、'.join(matched)}）",
                {"substitute": SUBSTITUTE.get(w, "")})
    else:
        add("OK", "IMAGE_BAN", "无禁用意象")

    # 4. 地名
    ph = [p for p in PLACE_BAN if p in body]
    called = PLACE_CALL_RE.findall(body)
    for c in called:
        if c not in ph:
            ph.append(c)
    # 只在正文里出现 2 次以上的"XX镇/村/谷"才认定为虚构地名（避免误伤"小镇""村子"）
    for w, suf in PLACE_SUFFIX_RE.findall(body):
        full = w + suf
        if full in PLACE_ORDINARY or w in PLACE_ORDINARY:
            continue
        if body.count(full) >= 2 and full not in ph:
            ph.append(full)
    if ph:
        add("ERROR", "PLACE_BAN", f"疑似过度文艺化地名：{'、'.join(sorted(set(ph)))}（用普通地理名词或不命名）")
    else:
        add("OK", "PLACE_BAN", "无过度文艺化地名")

    # 5. 结构套路
    struct_hits = []
    for name, pats in STRUCT_BAN:
        m = [p for p in pats if p in body]
        if m:
            struct_hits.append((name, m))
    if struct_hits:
        for name, m in struct_hits:
            add("ERROR", "STRUCT_BAN", f"命中结构套路「{name}」（命中：{'、'.join(m)}）")
    else:
        add("OK", "STRUCT_BAN", "无结构套路")

    # 6. 角色黑名单
    rh = [r for r in ROLE_BAN if r in body]
    if rh:
        add("ERROR", "ROLE_BAN", f"命中角色黑名单：{'、'.join(rh)}")
    else:
        add("OK", "ROLE_BAN", "无角色黑名单")

    # 7. 开头黑名单
    first = "\n".join([l for l in body.split("\n") if l.strip()][:3])
    first_start = first.strip()[:20]
    oh = [o for o in OPENING_BAN if o in first]
    for pat, label in OPENING_RE:
        if re.match(pat, first_start):
            oh.append(label)
    if oh:
        add("ERROR", "OPENING_BAN", f"开头黑名单：{'、'.join(sorted(set(oh)))}（第一段内）")
    else:
        add("OK", "OPENING_BAN", "开头未落入套路")

    # 8. 术语泄漏
    concept = meta.get("concept", "")
    conc_list = [c for c in re.split(r"[,，、/]|\s+", concept) if c]
    leaked = [t for t in TERM_BAN if t in body]
    # 概念词本身泄漏（若 meta 声明了）
    for c in conc_list:
        for frag in re.split(r"[\s\-—·、,，]+", c):
            if len(frag) >= 2 and frag in body:
                leaked.append(frag)
    leaked = sorted(set(leaked))
    if leaked:
        add("ERROR", "TERM_LEAK", f"正文泄漏概念术语：{'、'.join(leaked)}")
    else:
        add("OK", "TERM_LEAK", "无概念术语泄漏")

    # 9. 检验问题质量
    if quiz:
        vague = [w for w in ["你怎么看待", "有何启发", "谈谈你的看法", "你觉得呢", "有什么感想"] if w in quiz]
        if vague:
            add("ERROR", "QUIZ_VAGUE", f"检验问题过于空泛：{'、'.join(vague)}")
        else:
            add("OK", "QUIZ_VAGUE", "检验问题非空泛问法")
        if quiz.count("？") + quiz.count("?") < 2:
            add("WARN", "QUIZ_COUNT", "检验问题少于 2 个")
    else:
        add("WARN", "QUIZ", "未找到「第三部分：检验问题」段落")

    # 10. 解析段
    if analysis:
        add("OK", "ANALYSIS", "找到概念解析段落")
    else:
        add("WARN", "ANALYSIS", "未找到「第二部分：概念解析」段落")

    # 汇总
    errors = [i for i in result["issues"] if i["level"] == "ERROR"]
    warns = [i for i in result["issues"] if i["level"] == "WARN"]
    result["summary"] = {
        "chars": n,
        "cast": len(cast_list),
        "errors": len(errors),
        "warns": len(warns),
        "pass": (len(errors) == 0) and (not strict or len(warns) == 0),
    }
    return result


def run(path, strict=False):
    """检查一个文件；文件里若有多则寓言，逐则检查。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    chunks = split_fables(raw)
    results = [check_one(chunk, path, strict=strict) for chunk, _ in chunks]
    for i, r in enumerate(results, 1):
        if len(results) > 1:
            r["index"] = i
    return results


def render_one(result):
    L = []
    s = result["summary"]
    tag = f" #{result['index']}" if result.get("index") else ""
    L.append("=" * 62)
    L.append(f"寓言自检：{result['file']}{tag}")
    L.append("=" * 62)
    L.append(f"正文 {s['chars']} 字 | 角色 {s['cast']} 个 | ERROR {s['errors']} | WARN {s['warns']}")
    L.append("-" * 62)
    icon = {"ERROR": "[X]", "WARN": "[!]", "OK": "[ ]"}
    for i in result["issues"]:
        L.append(f"{icon[i['level']]} {i['code']:<12} {i['message']}")
        if i.get("substitute"):
            L.append(f"{'':<17}↳ 可用替身：{i['substitute']}")
    L.append("-" * 62)
    L.append("PASS" if s["pass"] else "FAIL")
    return "\n".join(L)


def render(results):
    out = [render_one(r) for r in results]
    ok = all(r["summary"]["pass"] for r in results)
    out.append("")
    if len(results) > 1:
        out.append(f"合计 {len(results)} 则：{'全部通过' if ok else '存在未通过项'}")
    if ok:
        out.append("提示：脚本只挡机械问题。仍需人读——角色是否在当解说员？结尾是否给了金句？")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="寓言文本自检")
    ap.add_argument("file", help="要检查的 markdown 文件")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="WARN 也算失败")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"文件不存在: {args.file}", file=sys.stderr)
        return 2

    results = run(args.file, strict=args.strict)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(render(results))
    return 0 if all(r["summary"]["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
