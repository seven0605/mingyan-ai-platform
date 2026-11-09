from __future__ import annotations

import json


VISUAL_STANDARD_LABELS = {
    "live-action": "真人写实影视资产",
    "guofeng-3d": "国风3D动画资产",
    "handpainted-3d2d": "手绘3渲2动画资产",
    "western-dark-medieval": "西方暗黑中世纪真人资产",
    "victorian-gothic": "维多利亚时代哥特真人资产",
}

COSTUME_ERA_LABELS = {
    "auto": "未指定朝代；必须根据已确认剧本判断现代或历史背景",
    "xia": "夏代",
    "shang": "商代",
    "zhou": "周代",
    "qin": "秦代",
    "han": "汉代",
    "three-kingdoms": "三国",
    "jin": "晋代",
    "northern-southern": "南北朝",
    "sui": "隋代",
    "tang": "唐代",
    "five-dynasties": "五代十国",
    "song": "宋代",
    "yuan": "元代",
    "ming": "明代",
    "qing": "清代",
}

ASSET_CARD_SYSTEM_PROMPT = """你是影视资产美术总监，负责把已确认剧本中的角色、场景和道具整理为可长期复用的制作级资产卡基础资料。

只返回一个 JSON 对象，格式必须严格为：
{"assets":[{"id":"原编号","kind":"character|scene|prop","name":"原名称","description":"...","visualAnchor":"...","continuityNotes":"..."}]}

绝对规则：
1. 输入中的每项资产必须且只能返回一次；id、kind、name 必须原样保留。
2. 不增加剧本没有的身份、人物关系、剧情事实、道具功能或历史结论。
3. description 说明资产在故事中的身份、用途和制作定位，必须具体，不写空泛风格口号。
4. visualAnchor 只写静态且肉眼可验证的视觉 DNA，必须足以让后续生图保持一致：
   - 单人角色：明确表观年龄、脸型、眉眼、鼻唇、肤色与皮肤质感、发型发色、身高体态、主造型轮廓、服装层级/材质/主色、鞋履、固定配饰和至少一个独特识别点。不得只写“真人写实”“漂亮”“古风”等空话。
   - 群体角色：明确人数范围、性别数量、年龄层、共同身份、不同脸、不同服装及统一画风，不锁定成同一张脸。
   - 场景：明确空间结构、入口与动线、前中后景、固定陈设、建筑和表面材质、主色、固定光源及至少三个永久地标；不得出现人物动作。
   - 道具：明确尺寸尺度、轮廓、结构、主辅材质、工艺、颜色、磨损、接口或纹样及至少两个唯一识别点；不得出现持有者和人物动作。
5. continuityNotes 分开写“必须固定”与“允许随剧情变化”的内容。固定项必须可检查；角色至少锁定脸、骨相、发色、体态和固定识别点，场景锁定布局与永久陈设，道具锁定尺寸、结构与材质。
6. 视觉标准只决定美术语言，不得用视觉标准名称代替具体设计。未指定朝代时必须从剧情判断：现代题材使用现代服装、建筑和物件，禁止擅自古装化。
7. 不写镜头、景别、运镜、表演、情绪变化、画面文字、水印或生图模型参数。
8. 每项 description 不少于 30 个中文字符，visualAnchor 不少于 80 个中文字符，continuityNotes 不少于 40 个中文字符。
"""


def _story_context(asset: dict, screenplay: dict) -> list[dict]:
    result: list[dict] = []
    kind = asset["kind"]
    name = asset["name"]
    for episode in screenplay.get("episodes", []):
        for scene in episode.get("scenes", []):
            relevant = (
                kind == "character" and name in scene.get("characters", [])
            ) or (
                kind == "scene" and name == scene.get("heading")
            ) or (
                kind == "prop" and name in scene.get("props", [])
            )
            if not relevant:
                continue
            result.append(
                {
                    "episodeNumber": episode.get("episodeNumber"),
                    "sceneIndex": scene.get("index"),
                    "heading": scene.get("heading"),
                    "characters": scene.get("characters", []),
                    "props": scene.get("props", []),
                    "objective": scene.get("objective", ""),
                    "obstacle": scene.get("obstacle", ""),
                    "beats": [
                        beat.get("text", "") for beat in scene.get("beats", [])
                    ],
                }
            )
    return result


def build_asset_card_messages(
    project_name: str,
    visual_standard: str,
    costume_era: str,
    assets: list[dict],
    screenplay: dict,
) -> list[dict[str, str]]:
    payload = {
        "projectName": project_name,
        "visualStandard": VISUAL_STANDARD_LABELS[visual_standard],
        "costumeEra": COSTUME_ERA_LABELS[costume_era],
        "assets": [
            {
                "id": asset["id"],
                "kind": asset["kind"],
                "name": asset["name"],
                "appearances": asset.get("appearances", []),
                "sourceRefs": asset.get("sourceRefs", []),
                "existingDescription": asset.get("description", ""),
                "existingVisualAnchor": asset.get("visualAnchor", ""),
                "existingContinuityNotes": asset.get("continuityNotes", ""),
                "confirmedStoryContext": _story_context(asset, screenplay),
            }
            for asset in assets
        ],
    }
    return [
        {"role": "system", "content": ASSET_CARD_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
