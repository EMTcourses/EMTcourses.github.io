# -*- coding: utf-8 -*-
"""重建课程索引站的数据，并注入 index.html。

只负责「数据」这一层：页面的 HTML/CSS/JS 你可以随便改，本脚本不碰，
它只替换 <script type="text/plain" id="data"> 节点里的那一行 base64。

用法（在「课程检索网站」目录下）：
    python 网站网页/build.py            # 重建数据并注入 网站网页/index.html
    python 网站网页/build.py --check    # 只重建并与页面里现有数据对比，不写任何文件
    python 网站网页/build.py --data     # 另存未编码的 site_data.json 供查看，不动页面

路径以本脚本所在的“网站网页/”的上一级（课程检索网站/）为根。

输入（全在本机，无需联网）：
    ../转写稿/*_转写稿.md      讲稿与句级时间戳（相对课程检索网站/）
    本地网页/源数据/bili.json           分P版合集的 91 集目录（B 站 pagelist API 原始返回）
    本地网页/源数据/view2.json          分组版合集的分组结构（B 站 view API 原始返回）
    本地网页/源数据/bili_map.json       本地文件名 -> 分P号
    本地网页/源数据/group_map.json      分P号 -> 分组序号 + 单集 bvid
    本地网页/源数据/alias_terms.json    别名映射，用于把搜索展开
    本地网页/源数据/alt_hints.json      搜不到时的替代说法提示
    本地网页/源数据/tagterms.json       可做自定义标签的术语

输出：
    网站网页/index.html        注入 base64 后的课程检索页面
    site_data.json             仅 --data 时生成，查看完可删
"""
import base64, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))       # .../课程检索网站/网站网页
ROOT = os.path.dirname(HERE)                             # .../课程检索网站
SRC = os.path.join(ROOT, "本地网页", "源数据")
TRANS = os.path.normpath(os.path.join(ROOT, "..", "转写稿"))
PAGE = os.path.join(HERE, "index.html")                  # 全站唯一的页面
OUT_JSON = os.path.join(ROOT, "site_data.json")

BV = "BV1EL4y1Y7Sa"          # 分P版合集，播放器与分P链接用
BV_SEASON = "BV1kL41187fZ"   # 分组版合集，单集链接用
UP = "云之阁"

# 首页「按主题」的按钮。想增删直接改这里，格式 [显示词, 悬停提示]（显示词即搜索词）
TOPICS = [
    ["变压器", "六、变压器"], ["电缆", "四、电缆"],
    ["MODELS", "二、基本操作 / 十、高级应用"], ["TACS", "二、基本操作"],
    ["输电线路", "三、架空输电线路"], ["雷电", "九、雷电过电压"],
    ["操作过电压", "八、操作过电压"], ["非线性", "五、非线性元件"],
    ["工频计算", "七、工频计算"], ["绝缘子", "九、雷电过电压"],
    ["避雷器", "八、操作过电压"], ["谐振", "八、操作过电压"],
    ["杆塔", "九、雷电过电压"], ["电机", "十、高级应用"],
    ["潮流", "十、高级应用"], ["IGBT", "十、高级应用"],
    ["频率扫描", "十、高级应用"], ["波阻抗", "三、架空输电线路"],
]

# 首页「按模型」按钮：[按钮文字, 悬停提示, 实际搜索词]
# 搜索词取语料里真实出现的写法（讲师多说「JMarti」而不带「模型」），命中数见建站说明
MODEL_TOPICS = [
    ["JMarti模型", "三、架空输电线路 / 四、电缆", "JMarti"],
    ["贝杰龙模型", "Bergeron 模型，多个分组", "贝杰龙"],
    ["PI模型", "π 模型，多个分组", "PI模型"],
    ["LCC", "线路 / 电缆参数计算", "LCC"],
    ["BCTRAN模型", "六、变压器", "BCTRAN"],
    ["XFMR模型", "六、变压器", "XFMR"],
    ["SAT饱和模型", "六、变压器", "SAT饱和模型"],
    ["Kizilcay模型", "RLC 集中参数等值，多个分组", "Kizilcay模型"],
    ["Heidler模型", "雷电流波形，九、雷电过电压", "Heidler"],
    ["电弧模型", "TACS / MODELS 电弧", "电弧"],
    ["统计开关", "八、操作过电压", "统计开关"],
    ["先导法", "绝缘子闪络判据，九、雷电过电压", "先导法"],
]

SEG = re.compile(r"^\[(\d\d):(\d\d):(\d\d(?:\.\d+)?)\]\s*(.+)$")


def rj(name):
    return json.load(io.open(os.path.join(SRC, name), encoding="utf-8"))


def read_transcripts():
    """返回 {本地讲名: [[秒, 句子], ...]}"""
    out = {}
    for fn in sorted(os.listdir(TRANS)):
        if not fn.endswith("_转写稿.md"):
            continue
        name = fn[: -len("_转写稿.md")]
        sents = []
        for ln in io.open(os.path.join(TRANS, fn), encoding="utf-8"):
            m = SEG.match(ln.strip())
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                txt = m.group(4).strip()
                if txt:
                    sents.append([round(t), txt])
        if sents:                      # 无解说的纯字幕视频没有句子，跳过
            out[name] = sents
    return out


def build():
    trans = read_transcripts()
    bmap = rj("bili_map.json")          # 本地讲名 -> {p, dur}
    gmap = rj("group_map.json")         # 分P号(字符串) -> {sec, secname, bvid}
    pages = rj("bili.json")["data"]     # 91 集目录
    secs = rj("view2.json")["data"]["ugc_season"]["sections"]
    at = rj("alias_terms.json")
    tags = rj("tagterms.json")

    lec, missing = [], []
    for name, sents in trans.items():
        if name not in bmap:
            missing.append(name)
            continue
        p = bmap[name]["p"]
        g = gmap.get(str(p)) or gmap.get(p) or {}
        item = {"p": p, "t": name, "d": bmap[name]["dur"], "s": sents,
                "g": g.get("sec", -1)}
        if g.get("bvid"):
            item["b2"] = g["bvid"]
        lec.append(item)
    lec.sort(key=lambda x: x["p"])

    cnt = {}
    for L in lec:
        cnt[L["g"]] = cnt.get(L["g"], 0) + 1
    groups = [{"i": i, "n": s["title"], "c": cnt[i]}
              for i, s in enumerate(secs) if cnt.get(i)]

    # alias：搜索词 -> 语料中的实际写法，用于把搜索展开（XFMR 也能搜到「X F M R」）
    # alt  ：搜不到时给出的替代说法提示；值为空数组表示「课程确实没讲」
    alias = dict(at.get("alias") or {})
    alt = rj("alt_hints.json")

    data = {
        "bv": BV, "up": UP, "n": len(lec),
        "lec": lec, "topics": TOPICS, "models": MODEL_TOPICS, "alt": alt,
        "groups": groups,
        "all": [{"p": x["page"], "t": x["part"], "d": x["duration"]} for x in pages],
        "season": rj("view2.json")["data"]["ugc_season"]["title"],
        "alias": alias,
        "terms": sorted({t.lower() for t in tags}),
    }
    return data, missing


DATA_RE = re.compile(r'(<script type="text/plain" id="data">)(.*?)(</script>)', re.S)


def page_data():
    """读出页面里现有的数据（解码后的 JSON 文本）。"""
    html = io.open(PAGE, encoding="utf-8").read()
    m = DATA_RE.search(html)
    return base64.b64decode(m.group(2).strip()).decode("utf-8") if m else ""


def inject(js_text):
    """把 base64 数据写进页面的 data 节点，页面其余部分原样保留。"""
    html = io.open(PAGE, encoding="utf-8").read()
    b64 = base64.b64encode(js_text.encode("utf-8")).decode("ascii")
    new, n = DATA_RE.subn(lambda m: m.group(1) + b64 + m.group(3), html)
    if n != 1:
        sys.exit(f"错误：在 {PAGE} 中找到 {n} 个 data 节点，应为 1 个")
    io.open(PAGE, "w", encoding="utf-8").write(new)
    return len(new.encode("utf-8"))


def main():
    args = set(sys.argv[1:])
    data, missing = build()
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    print(f"讲数 {len(data['lec'])}　分组 {len(data['groups'])}　"
          f"全集目录 {len(data['all'])}　别名 {len(data['alias'])}　"
          f"标签术语 {len(data['terms'])}")
    print(f"句子 {sum(len(L['s']) for L in data['lec'])}　"
          f"数据 {len(js.encode('utf-8'))/1024:.0f} KB")
    for L in data["lec"]:
        if L["g"] < 0:
            print(f"  ! 未归组：P{L['p']} {L['t']}")
    for m in missing:
        print(f"  ! 有讲稿但不在 bili_map 中：{m}")

    if "--check" in args:
        print("与页面里现有数据 " + ("一致" if page_data() == js else "不一致"))
        return

    if "--data" in args:
        io.open(OUT_JSON, "w", encoding="utf-8").write(js)
        print(f"已写 {OUT_JSON}（仅供查看，不参与发布）")
        return

    size = inject(js)
    print(f"已注入 {PAGE}，页面 {size/1024:.0f} KB")


if __name__ == "__main__":
    main()
