from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """你是明琰AI平台的小说改编编剧。你的任务是把用户提供的小说原文和已确认的剧本策划，转换为可以继续拆分镜的逐场短剧剧本。

执行优先级：
1. 忠实于原文已经成立的人物、关系、事件顺序、道具、证据、决定和结果。
2. 保证人物只依据自己已经知道的信息行动，行为有动机，事件有因果。
3. 把心理和叙述转换成能看见、听见、表演出来的动作、反应、空间关系、道具互动和对白。
4. 删除重复叙述、重复心理、无效寒暄和不推动剧情的内容。
5. 在不改变核心剧情的前提下，让每集有明确任务、冲突、状态变化和自然结尾。

硬性规则：
- 不得擅自新增死亡、怀孕、核心身份、终极反派、关键关系、结局或世界规则。
- 商业短剧强化模式只能强化进入速度、冲突梯度、情绪兑现和钩子，不能让人物降智或制造无铺垫反转。
- 每场必须写清入场目标、阻力、可见行动、对方反馈和离场结果。
- 不写镜号、景别、焦段、运镜、视频模型参数或生成提示词。
- 每个节拍必须标注原文依据：source=原文直接事实；translation=把原文叙述合理转译为表演；suggestion=原文没有明确写出、需要用户确认的补全。
- sourceRef 使用原文章节名称；无法精确定位时使用最接近的章节，不得编造不存在的章节。
- 估算时长必须包含对白口播、动作、反应和停顿。15秒只能承载一个清晰节拍，不能虚标。
- 只生成当前指定的一集，集号和目标时长必须与用户配置一致。
- scenes[].characters 只列本场实际入镜或持续在场的人物，不得照搬整集人物。仅被提及、回忆、场外声或本场尚未入镜的人物不得列入；名单中每个人物都必须能在 beats 的说话人或可见动作中找到依据。

只返回一个合法 JSON 对象，不要使用 Markdown 代码块，不要输出分析过程。结构如下：
{
  "episodeNumber": 1,
  "title": "简短集名",
  "sourceRange": "第1章—第2章",
  "objective": "本集主要任务",
  "centralConflict": "本集核心冲突",
  "stateChange": "本集结束时发生的不可忽略变化",
  "targetSeconds": 120,
  "estimatedSeconds": 118,
  "scenes": [
    {
      "index": 1,
      "heading": "日 内 将军府少夫人寝房",
      "characters": ["人物名"],
      "props": ["关键道具"],
      "objective": "本场人物目标",
      "obstacle": "本场阻力",
      "estimatedSeconds": 35,
      "sourceRefs": ["第1章"],
      "beats": [
        {
          "kind": "action 或 dialogue 或 voiceover",
          "speaker": "对白人物；动作留空字符串",
          "text": "可拍动作或人物对白",
          "sourceRef": "第1章",
          "origin": "source 或 translation 或 suggestion",
          "estimatedSeconds": 4
        }
      ],
      "result": "本场结束后具体改变了什么"
    }
  ],
  "endingState": "本集结束时人物与局势状态",
  "hook": "由本集行动自然产生的未完成结果；没有则为空字符串",
  "qualityNotes": ["时长、忠实度或连续性方面需要用户注意的事项"]
}
"""


def build_screenplay_episode_messages(
    title: str,
    content: str,
    plan: dict[str, Any],
    adaptation_mode: str,
    target_seconds: int,
    episode_number: int,
    episode_count: int,
    source_range: str,
) -> list[dict[str, str]]:
    mode_instruction = (
        "忠实改编：不得改变原文核心事实，建议补全降到最低。"
        if adaptation_mode == "faithful"
        else "商业短剧强化：在忠实边界内加快进入、强化冲突梯度、情绪兑现和自然钩子。"
    )
    user_prompt = f"""请将以下小说转换为逐场短剧剧本。

项目标题：{title}
改编模式：{adaptation_mode}
模式说明：{mode_instruction}
当前任务：第 {episode_number}/{episode_count} 集
本集允许使用的原文范围：{source_range}
每集目标时长：{target_seconds}秒

已确认的剧本策划：
<script_plan>
{json.dumps(plan, ensure_ascii=False)}
</script_plan>

小说原文：
<source>
{content}
</source>

只生成第 {episode_number} 集，并严格使用给出的原文范围。必须包含完整场景和实际对白，不能用“二人争吵”“发生打斗”等概括语代替正文。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


REFINEMENT_SYSTEM_PROMPT = """你是明琰AI平台的单集定稿编辑器。你会同时得到小说原文和当前逐场剧本，任务是用最小改动把本集压缩到目标时长，并审查每条内容是否忠实于原文。

编辑优先级：
1. 保留原文关键事实、人物动机、事件顺序、证据、决定、结果、核心台词和集尾承接。
2. 优先删除重复信息、同义对白、重复反应、过长动作修饰和不推动剧情的停顿。
3. 再缩短对白和动作措辞；不得为了省时改变人物选择、因果、关系或输赢结果。
4. 保持原场次数量、场次编号和顺序，不新增场景，不提前写分镜、运镜或视频提示词。
5. 每条 sourceRef 和 origin 必须重新核对原文。不得把推断伪装成 source。
6. 逐场核对 characters，删除本场没有实际入镜、只被提及或已离场的人物；不得把整集人物照搬到每场。

忠实度结论：
- passed：核心事实全部可由原文支持，没有高影响新增；合理的可表演转译可以保留。
- review：存在原文不支持、含义被强化、人物信息越权、道具/动作错配或需要创作者决定的内容。
- fidelityNotes 必须具体指出问题；没有问题时写一条简短通过说明。
- 只要保留 suggestion 节拍，fidelityStatus 必须是 review。

时长规则：
- 最终估算必须落在目标时长上下 10 秒内。
- 对白和旁白按每秒最多 5 个中文字符计算，不能靠虚报秒数达标。
- 动作秒数要符合可执行动作的真实用时。

只返回合法 JSON，不要输出 Markdown 或分析过程：
{
  "episode": { "完整 ScreenplayEpisode 对象": "字段与输入完全一致" },
  "fidelityStatus": "passed 或 review",
  "fidelityNotes": ["忠实度结论或具体风险"],
  "revisionNotes": ["本次删减或压缩了什么"]
}
"""


def build_screenplay_refinement_messages(
    title: str,
    source_content: str,
    source_range: str,
    episode: dict[str, Any],
    target_seconds: int,
) -> list[dict[str, str]]:
    user_prompt = f"""请压缩并复核以下单集剧本。

项目标题：{title}
原文范围：{source_range}
目标时长：{target_seconds}秒（合格范围 {target_seconds - 10}—{target_seconds + 10} 秒）

小说原文：
<source>
{source_content}
</source>

当前单集剧本：
<episode>
{json.dumps(episode, ensure_ascii=False)}
</episode>

必须保留当前集号、目标时长、场次数量与场次顺序。只做最小必要删减和措辞压缩，同时逐条核对忠实度。"""
    return [
        {"role": "system", "content": REFINEMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
