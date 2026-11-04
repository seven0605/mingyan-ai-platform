from __future__ import annotations

import re

CHAPTER_PATTERN = re.compile(
    r"^(第[0-9０-９一二三四五六七八九十百千万]{1,16}[章节回卷部]|楔子|序章|番外)\s*$",
    re.MULTILINE,
)

SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢"
    "邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷"
    "贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄穆萧尹姚邵湛汪"
    "祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄"
    "危江童颜郭梅林钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫经房裘缪干解应宗"
    "丁宣邓郁单杭洪包诸左石崔吉龚程嵇邢滑裴陆荣翁荀羊甄曲封储靳汲邴糜松井"
    "段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾甘厉戎祖武符刘景"
    "詹束龙叶司黎冷"
)

CHARACTER_ACTIONS = (
    "说道|开口|冷道|怒道|问道|喝道|命令|笑道|低声道|沉声道|淡淡道|平静道|"
    "脸色|神色|目光|眉头|眼底|咬牙|一怔|冷笑|转头|抬手|起身|走到|走进|走出|"
    "跪下|领命|闻言|看着|皱眉|震惊|愤怒|不敢置信"
)

CHARACTER_PATTERN = re.compile(
    rf"([{SURNAMES}][\u4e00-\u9fff]{{1,3}})(?=(?:{CHARACTER_ACTIONS}))"
)

LOCATION_TERMS = (
    "暗影阁大牢",
    "大将军府",
    "太医院",
    "公主府",
    "御书房",
    "将军府",
    "暗影阁",
    "祠堂",
    "皇宫",
    "宫殿",
    "大殿",
    "大牢",
    "内室",
    "长廊",
    "前院",
    "后院",
    "院外",
    "湖边",
    "湖里",
    "房间",
    "房里",
    "城门",
    "王府",
    "客栈",
    "酒楼",
    "街道",
    "战场",
    "山谷",
    "森林",
    "宗门",
    "洞府",
)


def split_chapters(text: str) -> list[dict[str, object]]:
    matches = list(CHAPTER_PATTERN.finditer(text))
    if not matches:
        return [{"index": 1, "title": "全文", "content": text.strip()}]

    chapters: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append(
            {
                "index": index + 1,
                "title": match.group(1),
                "content": text[match.end() : end].strip(),
            }
        )
    return chapters


def chapter_indexes(term: str, chapters: list[dict[str, object]]) -> list[int]:
    return [
        int(chapter["index"])
        for chapter in chapters
        if term in str(chapter["content"])
    ]


def extract_characters(text: str, chapters: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates = set(CHARACTER_PATTERN.findall(text))
    characters = []
    for name in candidates:
        if name[-1] in "的地得着了们来去要也" or len(set(name)) == 1:
            continue
        mentions = text.count(name)
        if mentions < 2:
            continue
        characters.append(
            {
                "name": name,
                "mentions": mentions,
                "chapters": chapter_indexes(name, chapters),
            }
        )
    return sorted(characters, key=lambda item: (-int(item["mentions"]), str(item["name"])))[:16]


def extract_scenes(text: str, chapters: list[dict[str, object]]) -> list[dict[str, object]]:
    found = [term for term in LOCATION_TERMS if term in text]
    selected: list[str] = []
    for term in found:
        if any(term in longer_term for longer_term in selected):
            continue
        selected.append(term)

    scenes = [
        {
            "name": term,
            "mentions": text.count(term),
            "chapters": chapter_indexes(term, chapters),
        }
        for term in selected
    ]
    return sorted(scenes, key=lambda item: (-int(item["mentions"]), str(item["name"])))[:16]


def text_anchor(paragraphs: list[str], from_end: bool = False) -> str:
    selected = paragraphs[-2:] if from_end else paragraphs[:4]
    return "".join(selected)[:120]


def extract_plot_nodes(chapters: list[dict[str, object]]) -> list[dict[str, object]]:
    nodes = []
    for chapter in chapters:
        content = str(chapter["content"])
        paragraphs = [line.strip() for line in content.splitlines() if line.strip()]
        nodes.append(
            {
                "index": int(chapter["index"]),
                "title": str(chapter["title"]),
                "charCount": len(content),
                "opening": text_anchor(paragraphs),
                "closing": text_anchor(paragraphs, from_end=True),
            }
        )
    return nodes


def analyze_story(text: str) -> dict[str, object]:
    chapters = split_chapters(text)
    return {
        "characters": extract_characters(text, chapters),
        "scenes": extract_scenes(text, chapters),
        "plotNodes": extract_plot_nodes(chapters),
    }
