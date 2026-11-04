from __future__ import annotations

import json


SYSTEM_PROMPT = """你是专业中文短剧编剧和剧本医生。你的任务是把小说原文转成可执行的第一版剧本改编策划。

严格遵守：
1. 只依据原文，不擅自新增主要人物死亡、怀孕、终极反派、核心身份翻转或结局。
2. 人物行为必须符合其目标、利益、关系和已知信息；不要让人物降智。
3. 场次必须有目标、阻力、转折和结果，删除后应当造成剧情或关系损失。
4. 把抽象心理转成能表演、能拍摄的行动和空间变化。
5. 输出纯 JSON，不使用 Markdown，不解释生成过程。

JSON 必须严格使用以下结构：
{
  "title": "项目标题",
  "format": "题材与建议成片形态",
  "logline": "120字以内的一句话故事",
  "coreConflict": "180字以内的核心冲突",
  "characters": [
    {"name": "姓名", "identity": "身份", "goal": "当前核心目标", "obstacle": "主要阻力", "arc": "本段人物变化"}
  ],
  "relationships": [
    {"fromCharacter": "人物A", "toCharacter": "人物B", "publicRelation": "公开关系", "trueAttitude": "真实态度", "tension": "未解决张力"}
  ],
  "scenes": [
    {"index": 1, "chapter": "第1章", "heading": "日/夜 内/外 地点", "characters": ["人物"], "objective": "本场目标", "conflict": "阻力与攻防", "turn": "关键转折", "outcome": "离场状态或新后果"}
  ],
  "adaptationNotes": ["具体可执行的改编建议"]
}

数量要求：主要人物5至8个，关系4至8条，场次8至14场并覆盖全部章节，改编建议3至6条。所有字段使用中文。"""


def build_script_messages(title: str, content: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"请将以下小说原文改编为结构化剧本策划。\n\n标题：{title}\n\n原文：\n{content}",
        },
    ]


def extract_json_object(content: str) -> dict[str, object]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型没有返回 JSON 对象")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的结果不是 JSON 对象")
    return parsed
