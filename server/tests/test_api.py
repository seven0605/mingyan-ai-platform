from pathlib import Path
import json
import sqlite3

import httpx
from fastapi.testclient import TestClient

from server.app import asset_aspect_ratio, create_app, is_collective_character


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


def test_collective_characters_use_widescreen() -> None:
    assert is_collective_character("character", "萧府护卫们") is True
    assert is_collective_character("character", "暗影卫众") is True
    assert is_collective_character("character", "云子姝") is False
    assert asset_aspect_ratio("live-action", "character", "萧府护卫们") == "16:9"
    assert asset_aspect_ratio("live-action", "character", "云子姝") == "9:16"


def test_project_lifecycle_persists(tmp_path: Path) -> None:
    credentials = MemoryCredentialStore()
    invalid_screenplay = False
    invalid_storyboard = False
    image_generation_failed = False
    image_requests: list[dict] = []

    script_plan_payload = {
        "title": "凤掌九天",
        "format": "古装重生女频短剧",
        "logline": "重生公主在将军府夺回尊严并追查前世阴谋。",
        "coreConflict": "云子姝必须在萧家的栽赃与皇权棋局中证明清白并主动反击。",
        "characters": [
            {
                "name": "云子姝",
                "identity": "公主",
                "goal": "摆脱萧家并查明真相",
                "obstacle": "萧家构陷",
                "arc": "从隐忍到主动掌控",
            }
        ],
        "relationships": [
            {
                "fromCharacter": "云子姝",
                "toCharacter": "萧云衡",
                "publicRelation": "夫妻",
                "trueAttitude": "决意割裂",
                "tension": "赐婚与和离冲突",
            }
        ],
        "scenes": [
            {
                "index": 1,
                "chapter": "第1章",
                "heading": "日 内 云子姝卧房",
                "characters": ["云子姝", "萧云衡"],
                "objective": "云子姝确认重生时点",
                "conflict": "萧云衡逼她认罪",
                "turn": "云子姝以公主身份反制",
                "outcome": "她决定请太医验明真相",
            }
        ],
        "adaptationNotes": ["保留重生醒来的身份反差。"],
    }

    screenplay_payload = {
        "adaptationMode": "faithful",
        "targetSeconds": 120,
        "episodeCount": 2,
        "episodes": [
            {
                "episodeNumber": 1,
                "title": "重生问罪",
                "sourceRange": "第1章",
                "objective": "云子姝确认处境并拒绝认罪",
                "centralConflict": "萧云衡逼迫云子姝认下推人落水",
                "stateChange": "云子姝决定请太医验明真相",
                "targetSeconds": 120,
                "estimatedSeconds": 20,
                "scenes": [
                    {
                        "index": 1,
                        "heading": "日 内 云子姝卧房",
                        "characters": ["云子姝", "萧云衡"],
                        "props": [],
                        "objective": "确认重生时点",
                        "obstacle": "萧云衡逼她认罪",
                        "estimatedSeconds": 20,
                        "sourceRefs": ["第1章"],
                        "beats": [
                            {
                                "kind": "action",
                                "speaker": "",
                                "text": "云子姝从地上撑起身，盯住萧云衡。",
                                "sourceRef": "第1章",
                                "origin": "translation",
                                "estimatedSeconds": 3,
                            },
                            {
                                "kind": "dialogue",
                                "speaker": "云子姝",
                                "text": "萧云衡，你要造反吗？",
                                "sourceRef": "第1章",
                                "origin": "source",
                                "estimatedSeconds": 1,
                            },
                        ],
                        "result": "云子姝夺回对话主动权",
                    }
                ],
                "endingState": "双方公开对立",
                "hook": "云子姝命人进宫请太医",
                "qualityNotes": ["下一集需承接太医验伪。"],
            },
            {
                "episodeNumber": 2,
                "title": "太医验伪",
                "sourceRange": "第2章",
                "objective": "用诊断击破构陷",
                "centralConflict": "萧家阻止真相公开",
                "stateChange": "云子姝取得反击依据",
                "targetSeconds": 120,
                "estimatedSeconds": 20,
                "scenes": [
                    {
                        "index": 1,
                        "heading": "日 内 暗影阁大牢",
                        "characters": ["云子姝", "萧云衡"],
                        "props": ["诊脉记录"],
                        "objective": "确认诊断结果",
                        "obstacle": "萧云衡拒绝接受事实",
                        "estimatedSeconds": 20,
                        "sourceRefs": ["第2章"],
                        "beats": [
                            {
                                "kind": "action",
                                "speaker": "",
                                "text": "云子姝把诊脉记录推到萧云衡面前。",
                                "sourceRef": "第2章",
                                "origin": "translation",
                                "estimatedSeconds": 4,
                            }
                        ],
                        "result": "构陷失去依据",
                    }
                ],
                "endingState": "云子姝掌握主动",
                "hook": "",
                "qualityNotes": ["保持诊断证据连续。"],
            },
        ],
        "continuityNotes": ["云子姝已公开拒绝认罪。", "诊脉记录由云子姝掌握。"],
    }

    def storyboard_payload() -> dict:
        groups = []
        for index in range(1, 9):
            start = (index - 1) * 15
            end = 110 if index == 8 else index * 15
            duration = end - start
            groups.append(
                {
                    "index": index,
                    "sceneIndex": 1,
                    "startSeconds": start,
                    "endSeconds": end,
                    "durationSeconds": duration,
                    "purpose": "推进问罪冲突",
                    "hookType": "升级",
                    "metadata": "第1集 第1场 日内 卧房",
                    "sceneDescription": "云子姝位于床榻右侧，萧云衡站在门口左侧。",
                    "firstFrameLock": "承接上一帧人物位置与朝向，服装和道具不变。",
                    "segments": [
                        {
                            "startSeconds": 0,
                            "endSeconds": duration,
                            "camera": "Medium shot, eye level, slow dolly in",
                            "action": "云子姝稳住身体并直视萧云衡。",
                            "motionVisual": "controlled forward motion, stable continuity",
                            "expression": "目光由克制转为冷厉。",
                            "environment": "日光从格窗照入，室内陈设保持稳定。",
                            "effects": "无",
                            "sound": "衣料摩擦声与压低的弦乐。",
                        }
                    ],
                    "qualityBase": "电影级写实画质与稳定时序",
                    "visualStyle": "古装写实，冷色日光",
                    "subjects": ["云子姝白色中衣", "萧云衡玄色将军服"],
                    "spatialRelations": "云子姝画面右侧，萧云衡画面左侧，相距两米。",
                    "actionTimeline": "0秒对峙，随后情绪逐步升级。",
                    "cameraLanguage": "中景缓推，不越轴。",
                    "emotionalTurn": "压抑→确认→反击",
                    "keyDialogue": "萧云衡，你要造反吗？",
                    "negativePrompt": "人物漂移、空间跳变、肢体畸形、口型错位、穿模、闪烁",
                    "generationParams": "16:9，24fps，写实电影风格，中等运动强度",
                    "videoPrompt": "古装写实卧房，中景缓推，云子姝冷静反击，保持人物位置与服装连续。",
                }
            )
        return {
            "episodeNumber": 1,
            "episodeTitle": "重生问罪",
            "styleBible": "古装写实电影质感，冷色日光，服装、发型和空间轴线全程一致。",
            "groups": groups,
            "continuityNotes": ["人物服装、伤势、站位与上一组末帧严格承接。"],
        }

    def model_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example.com":
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\n",
                headers={"content-type": "image/png"},
            )
        if request.url.path == "/v1/media/generate":
            assert request.headers["Authorization"] == "Bearer image-secret-not-for-sqlite"
            request_payload = json.loads(request.content)
            image_requests.append(request_payload)
            assert request_payload["model"] == "tt-image-2.5"
            assert "云子姝" in request_payload["prompt"]
            assert request_payload["params"]["aspect_ratio"] == "9:16"
            assert request_payload["params"]["resolution"] == "1K"
            if len(image_requests) == 1:
                assert "images" not in request_payload["params"]
            else:
                assert request_payload["params"]["images"][0].startswith(
                    "data:image/png;base64,"
                )
                assert "V1身份参考硬锁" in request_payload["prompt"]
            return httpx.Response(
                200,
                json={"code": 200, "data": {"task_id": "image-task-1"}},
            )
        if request.url.path == "/v1/media/status":
            assert request.headers["Authorization"] == "Bearer image-secret-not-for-sqlite"
            assert request.url.params["task_id"] == "image-task-1"
            if image_generation_failed:
                return httpx.Response(
                    200,
                    json={
                        "task_id": "image-task-1",
                        "state": "failed",
                        "is_final": True,
                        "result_url": "",
                        "error": "模拟生图失败",
                        "cost": 0,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "task_id": "image-task-1",
                    "state": "success",
                    "is_final": True,
                    "result_url": "https://cdn.example.com/yun-zishu.png",
                    "error": "",
                    "cost": 0.23,
                },
            )
        if request.url.path == "/v1/models":
            assert request.headers["Authorization"] in {
                "Bearer secret-not-for-sqlite",
                "Bearer image-secret-not-for-sqlite",
            }
            return httpx.Response(
                200,
                json={"data": [{"id": "example-chat"}, {"id": "tt-image-2.5"}]},
            )
        assert request.headers["Authorization"] == "Bearer secret-not-for-sqlite"
        assert request.url == "https://example.com/v1/chat/completions"
        request_payload = json.loads(request.content)
        assert request_payload["model"] == "example-chat"
        assert "云子姝" in request_payload["messages"][1]["content"]
        if "七维描述" in request_payload["messages"][0]["content"]:
            if invalid_storyboard:
                content = {"bad": True}
            else:
                batch_input = json.loads(
                    request_payload["messages"][1]["content"].split("\n", 1)[1]
                )
                group_indexes = {
                    item["index"]
                    for item in batch_input["authoritativeGroupBlueprints"]
                }
                content = storyboard_payload()
                content["groups"] = [
                    group for group in content["groups"]
                    if group["index"] in group_indexes
                ]
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
            )
        if "单集定稿编辑器" in request_payload["messages"][0]["content"]:
            episode_index = (
                0 if '"episodeNumber": 1' in request_payload["messages"][1]["content"] else 1
            )
            refined_episode = json.loads(
                json.dumps(screenplay_payload["episodes"][episode_index], ensure_ascii=False)
            )
            if episode_index == 0:
                refined_episode["scenes"][0]["beats"][0]["estimatedSeconds"] = 108
            else:
                refined_episode["scenes"][0]["beats"][0]["estimatedSeconds"] = 110
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "episode": refined_episode,
                                        "fidelityStatus": "passed",
                                        "fidelityNotes": ["关键事实均可追溯至对应原文章节。"],
                                        "revisionNotes": ["删除重复反应并压缩动作措辞。"],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            )
        if "逐场短剧剧本" in request_payload["messages"][0]["content"]:
            if invalid_screenplay:
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": '{"bad": true}'}}]},
                )
            episode_index = (
                0 if "第 1/2 集" in request_payload["messages"][1]["content"] else 1
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    screenplay_payload["episodes"][episode_index],
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(script_plan_payload, ensure_ascii=False)}}
                ]
            },
        )

    model_transport = httpx.MockTransport(model_handler)
    with TestClient(
        create_app(
            data_dir=tmp_path,
            static_dir=Path("missing"),
            credential_store=credentials,
            model_transport=model_transport,
        )
    ) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        assert client.get("/api/projects").json() == []

        empty_settings = client.get("/api/settings/text-model")
        assert empty_settings.status_code == 200
        assert empty_settings.json()["configured"] is False

        configured = client.put(
            "/api/settings/text-model",
            json={
                "baseUrl": "https://example.com/v1/",
                "model": "example-chat",
                "apiKey": "secret-not-for-sqlite",
            },
        )
        assert configured.status_code == 200
        assert configured.json() == {
            "provider": "openai-compatible",
            "baseUrl": "https://example.com/v1",
            "model": "example-chat",
            "hasCredential": True,
            "configured": True,
            "updatedAt": configured.json()["updatedAt"],
        }
        assert "apiKey" not in configured.json()
        assert credentials.values["text-model-api-key"] == "secret-not-for-sqlite"

        connection = client.post("/api/settings/text-model/test")
        assert connection.status_code == 200
        assert connection.json()["connected"] is True
        assert connection.json()["model"] == "example-chat"
        assert connection.json()["message"] == "鉴权成功，模型可用"

        empty_image_settings = client.get("/api/settings/image-model")
        assert empty_image_settings.status_code == 200
        assert empty_image_settings.json()["configured"] is False

        configured_image = client.put(
            "/api/settings/image-model",
            json={
                "baseUrl": "https://example.com/v1/",
                "model": "tt-image-2.5",
                "apiKey": "image-secret-not-for-sqlite",
            },
        )
        assert configured_image.status_code == 200
        assert configured_image.json() == {
            "provider": "buming-openai-compatible",
            "baseUrl": "https://example.com/v1",
            "model": "tt-image-2.5",
            "hasCredential": True,
            "configured": True,
            "updatedAt": configured_image.json()["updatedAt"],
        }
        assert "apiKey" not in configured_image.json()
        assert credentials.values["image-model-api-key"] == "image-secret-not-for-sqlite"

        image_connection = client.post("/api/settings/image-model/test")
        assert image_connection.status_code == 200
        assert image_connection.json()["connected"] is True
        assert image_connection.json()["model"] == "tt-image-2.5"
        assert "未生成图片" in image_connection.json()["message"]

        created = client.post(
            "/api/projects",
            json={"name": "跨平台测试", "description": "Mac 与 Windows 共用数据结构"},
        )
        assert created.status_code == 201
        project = created.json()
        assert project["stage"] == "text"
        assert client.get(f"/api/projects/{project['id']}/source").json() is None

        source_text = (
            "第1章\n云子姝走进祠堂。\n云子姝冷笑着看向众人。\n"
            "第2章\n萧云衡脸色一沉。\n萧云衡走进暗影阁大牢。"
        )
        saved_source = client.put(
            f"/api/projects/{project['id']}/source",
            json={"title": "测试原文", "content": source_text},
        )
        assert saved_source.status_code == 200
        assert saved_source.json()["charCount"] == len(source_text)
        assert saved_source.json()["chapterCount"] == 2

        analysis = client.post(f"/api/projects/{project['id']}/analysis")
        assert analysis.status_code == 200
        analysis_data = analysis.json()
        assert analysis_data["engine"] == "local-v1"
        assert len(analysis_data["plotNodes"]) == 2
        assert {item["name"] for item in analysis_data["characters"]} >= {
            "云子姝",
            "萧云衡",
        }
        assert {item["name"] for item in analysis_data["scenes"]} >= {
            "祠堂",
            "暗影阁大牢",
        }

        script_plan = client.post(f"/api/projects/{project['id']}/script-plan")
        assert script_plan.status_code == 200
        script_plan_data = script_plan.json()
        assert script_plan_data["model"] == "example-chat"
        assert script_plan_data["title"] == "凤掌九天"
        assert script_plan_data["scenes"][0]["heading"] == "日 内 云子姝卧房"

        screenplay = client.post(
            f"/api/projects/{project['id']}/screenplay",
            json={
                "adaptationMode": "faithful",
                "targetSeconds": 120,
                "episodeCount": 2,
            },
        )
        assert screenplay.status_code == 200
        screenplay_data = screenplay.json()
        assert screenplay_data["episodeCount"] == 2
        assert screenplay_data["episodes"][0]["title"] == "重生问罪"
        assert screenplay_data["episodes"][0]["scenes"][0]["beats"][1]["estimatedSeconds"] == 2
        assert screenplay_data["episodes"][0]["estimatedSeconds"] == 5
        assert screenplay_data["status"] == "draft"
        assert screenplay_data["approvedAt"] is None

        blocked_stage = client.patch(
            f"/api/projects/{project['id']}/stage",
            json={"stage": "storyboard"},
        )
        assert blocked_stage.status_code == 409
        blocked_storyboard = client.post(
            f"/api/projects/{project['id']}/storyboards/1",
            json={"targetModel": "seedance-2.0", "aspectRatio": "16:9"},
        )
        assert blocked_storyboard.status_code == 409

        invalid_screenplay = True
        failed_regeneration = client.post(
            f"/api/projects/{project['id']}/screenplay",
            json={
                "adaptationMode": "faithful",
                "targetSeconds": 120,
                "episodeCount": 2,
            },
        )
        assert failed_regeneration.status_code == 502
        preserved_screenplay = client.get(
            f"/api/projects/{project['id']}/screenplay"
        ).json()
        assert preserved_screenplay["episodes"][0]["title"] == "重生问罪"

        editable_screenplay = {
            key: preserved_screenplay[key]
            for key in (
                "adaptationMode",
                "targetSeconds",
                "episodeCount",
                "episodes",
                "continuityNotes",
            )
        }
        editable_screenplay["episodes"][0]["scenes"][0]["beats"][0]["text"] = (
            "云子姝起身，直视萧云衡。"
        )
        editable_screenplay["episodes"][0]["scenes"][0]["beats"][0]["estimatedSeconds"] = 108
        editable_screenplay["episodes"][1]["scenes"][0]["beats"][0]["estimatedSeconds"] = 110
        saved_screenplay = client.put(
            f"/api/projects/{project['id']}/screenplay",
            json=editable_screenplay,
        )
        assert saved_screenplay.status_code == 200
        assert saved_screenplay.json()["status"] == "draft"
        assert saved_screenplay.json()["episodes"][0]["estimatedSeconds"] == 110
        assert saved_screenplay.json()["episodes"][0]["fidelityStatus"] == "unchecked"

        blocked_approval = client.post(
            f"/api/projects/{project['id']}/screenplay/approve"
        )
        assert blocked_approval.status_code == 409

        refined_first = client.post(
            f"/api/projects/{project['id']}/screenplay/episodes/1/refine"
        )
        assert refined_first.status_code == 200
        assert refined_first.json()["episodes"][0]["estimatedSeconds"] == 110
        assert refined_first.json()["episodes"][0]["fidelityStatus"] == "passed"
        assert refined_first.json()["episodes"][1]["fidelityStatus"] == "unchecked"

        refined_second = client.post(
            f"/api/projects/{project['id']}/screenplay/episodes/2/refine"
        )
        assert refined_second.status_code == 200
        assert refined_second.json()["episodes"][1]["fidelityStatus"] == "passed"
        assert any(
            note.startswith("AI定稿：")
            for note in refined_second.json()["episodes"][1]["qualityNotes"]
        )

        approved_screenplay = client.post(
            f"/api/projects/{project['id']}/screenplay/approve"
        )
        assert approved_screenplay.status_code == 200
        assert approved_screenplay.json()["status"] == "approved"
        assert approved_screenplay.json()["approvedAt"] is not None

        updated = client.patch(
            f"/api/projects/{project['id']}/stage",
            json={"stage": "storyboard"},
        )
        assert updated.status_code == 200
        assert updated.json()["stage"] == "storyboard"

        storyboard = client.post(
            f"/api/projects/{project['id']}/storyboards/1",
            json={"targetModel": "seedance-2.0", "aspectRatio": "16:9"},
        )
        assert storyboard.status_code == 200
        storyboard_data = storyboard.json()
        assert storyboard_data["episodeNumber"] == 1
        assert storyboard_data["totalSeconds"] == 110
        assert len(storyboard_data["groups"]) == 8
        assert storyboard_data["groups"][-1]["endSeconds"] == 110
        assert storyboard_data["groups"][-1]["durationSeconds"] == 5

        editable_storyboard = {
            key: storyboard_data[key]
            for key in (
                "episodeNumber",
                "episodeTitle",
                "styleBible",
                "groups",
                "continuityNotes",
            )
        }
        editable_storyboard["groups"][0]["purpose"] = "人工调整后的镜头组目的"
        saved_storyboard = client.put(
            f"/api/projects/{project['id']}/storyboards/1",
            json=editable_storyboard,
        )
        assert saved_storyboard.status_code == 200
        assert saved_storyboard.json()["groups"][0]["purpose"] == "人工调整后的镜头组目的"

        invalid_edit = json.loads(json.dumps(editable_storyboard, ensure_ascii=False))
        invalid_edit["groups"][0]["endSeconds"] = 14
        rejected_edit = client.put(
            f"/api/projects/{project['id']}/storyboards/1",
            json=invalid_edit,
        )
        assert rejected_edit.status_code == 422
        assert client.get(f"/api/projects/{project['id']}/storyboards").json()[0][
            "groups"
        ][0]["purpose"] == "人工调整后的镜头组目的"

        invalid_storyboard = True
        failed_storyboard = client.post(
            f"/api/projects/{project['id']}/storyboards/1",
            json={"targetModel": "sora-2", "aspectRatio": "9:16"},
        )
        assert failed_storyboard.status_code == 502
        preserved_storyboard = client.get(
            f"/api/projects/{project['id']}/storyboards"
        ).json()
        assert len(preserved_storyboard) == 1
        assert preserved_storyboard[0]["targetModel"] == "seedance-2.0"

        assert client.get(f"/api/projects/{project['id']}/assets").json() is None
        extracted_assets = client.post(
            f"/api/projects/{project['id']}/assets/extract"
        )
        assert extracted_assets.status_code == 200
        asset_library = extracted_assets.json()
        assert {item["kind"] for item in asset_library["items"]} == {
            "character",
            "scene",
            "prop",
        }
        assert asset_library["standard"] == {
            "visualStandard": "live-action",
            "costumeEra": "auto",
        }
        assert {item["name"] for item in asset_library["items"] if item["kind"] == "character"} >= {
            "云子姝",
            "萧云衡",
        }
        assert "诊脉记录" in {
            item["name"] for item in asset_library["items"] if item["kind"] == "prop"
        }
        assert client.get(f"/api/projects/{project['id']}/tasks").json() == []
        assert client.get(
            f"/api/projects/{project['id']}/assets/batch-plan"
        ).json() is None

        editable_assets = {
            "items": asset_library["items"],
            "standard": {
                "visualStandard": "handpainted-3d2d",
                "costumeEra": "ming",
            },
        }
        yun_zishu = next(
            item for item in editable_assets["items"] if item["name"] == "云子姝"
        )
        yun_zishu["referencePrompt"] = "【角色资产卡｜云子姝】按手绘3渲2固定四宫格规则生成"
        yun_zishu["promptStandardSignature"] = (
            "handpainted-3d2d|ming|2026-11-04.8"
        )
        original_prompt = yun_zishu["referencePrompt"]
        yun_zishu["visualAnchor"] = "冷白肤色、素白中衣、长发凌乱、目光冷厉"
        yun_zishu["status"] = "confirmed"
        saved_assets = client.put(
            f"/api/projects/{project['id']}/assets", json=editable_assets
        )
        assert saved_assets.status_code == 200
        assert next(
            item for item in saved_assets.json()["items"] if item["name"] == "云子姝"
        )["status"] == "confirmed"
        assert saved_assets.json()["standard"] == editable_assets["standard"]
        assert next(
            item for item in saved_assets.json()["items"] if item["name"] == "云子姝"
        )["referencePrompt"] == original_prompt

        refreshed_assets = client.post(
            f"/api/projects/{project['id']}/assets/extract"
        )
        assert refreshed_assets.status_code == 200
        assert refreshed_assets.json()["standard"] == editable_assets["standard"]
        saved_assets = refreshed_assets

        invalid_standard = json.loads(json.dumps(editable_assets, ensure_ascii=False))
        invalid_standard["standard"]["visualStandard"] = "unknown-style"
        assert client.put(
            f"/api/projects/{project['id']}/assets", json=invalid_standard
        ).status_code == 422

        yun_zishu_id = next(
            item for item in saved_assets.json()["items"] if item["name"] == "云子姝"
        )["id"]
        xiao_yunheng_id = next(
            item for item in saved_assets.json()["items"] if item["name"] == "萧云衡"
        )["id"]
        unconfirmed_batch = client.post(
            f"/api/projects/{project['id']}/assets/batch-plan",
            json={"assetIds": [xiao_yunheng_id]},
        )
        assert unconfirmed_batch.status_code == 409
        generated_assets = client.post(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images"
        )
        assert generated_assets.status_code == 200
        generated_yun_zishu = next(
            item
            for item in generated_assets.json()["items"]
            if item["name"] == "云子姝"
        )
        assert len(generated_yun_zishu["referenceImages"]) == 1
        generated_image = generated_yun_zishu["referenceImages"][0]
        assert generated_image["model"] == "tt-image-2.5"
        assert generated_image["aspectRatio"] == "9:16"
        assert generated_image["resolution"] == "1K"
        assert generated_image["cost"] == 0.23
        assert generated_image["identityReferenceImageId"] == ""
        assert generated_yun_zishu["primaryReferenceImageId"] == generated_image["id"]
        generated_tasks = client.get(f"/api/projects/{project['id']}/tasks")
        assert generated_tasks.status_code == 200
        assert len(generated_tasks.json()) == 1
        assert generated_tasks.json()[0] == {
            "id": generated_image["id"],
            "projectId": project["id"],
            "type": "asset-image",
            "status": "completed",
            "title": "云子姝参考图 V1",
            "assetId": yun_zishu_id,
            "assetKind": "character",
            "providerTaskId": "image-task-1",
            "model": "tt-image-2.5",
            "resultUrl": generated_image["url"],
            "cost": 0.23,
            "batchId": "",
            "error": "",
            "attemptCount": 1,
            "createdAt": generated_image["createdAt"],
            "updatedAt": generated_image["createdAt"],
        }
        local_image = client.get(generated_image["url"])
        assert local_image.status_code == 200
        assert local_image.headers["content-type"] == "image/png"
        assert local_image.content.startswith(b"\x89PNG")

        batch_plan = client.post(
            f"/api/projects/{project['id']}/assets/batch-plan",
            json={"assetIds": [yun_zishu_id]},
        )
        assert batch_plan.status_code == 200
        assert batch_plan.json()["current"] is True
        assert batch_plan.json()["costSampleCount"] == 1
        assert batch_plan.json()["estimatedUnitCost"] == 0.23
        assert batch_plan.json()["estimatedTotalCost"] == 0.23
        assert batch_plan.json()["items"][0]["name"] == "云子姝"
        assert batch_plan.json()["items"][0]["existingVersionCount"] == 1
        assert batch_plan.json()["items"][0]["prompt"] == original_prompt

        image_generation_failed = True
        failed_image_generation = client.post(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images"
        )
        assert failed_image_generation.status_code == 502
        preserved_after_image_failure = client.get(
            f"/api/projects/{project['id']}/assets"
        ).json()
        assert len(next(
            item
            for item in preserved_after_image_failure["items"]
            if item["name"] == "云子姝"
        )["referenceImages"]) == 1
        image_generation_failed = False

        second_generation = client.post(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images"
        )
        assert second_generation.status_code == 200
        second_yun_zishu = next(
            item
            for item in second_generation.json()["items"]
            if item["name"] == "云子姝"
        )
        assert len(second_yun_zishu["referenceImages"]) == 2
        assert second_yun_zishu["primaryReferenceImageId"] == generated_image["id"]
        assert client.get(
            f"/api/projects/{project['id']}/assets/batch-plan"
        ).json()["current"] is False
        second_image = second_yun_zishu["referenceImages"][1]
        assert second_image["identityReferenceImageId"] == generated_image["id"]
        assert "V1身份参考硬锁" in second_image["prompt"]
        assert len(client.get(f"/api/projects/{project['id']}/tasks").json()) == 2
        missing_primary = client.put(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images/00000000-0000-4000-8000-000000000000/primary"
        )
        assert missing_primary.status_code == 404
        selected_primary = client.put(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images/{second_image['id']}/primary"
        )
        assert selected_primary.status_code == 200
        selected_yun_zishu = next(
            item
            for item in selected_primary.json()["items"]
            if item["name"] == "云子姝"
        )
        assert selected_yun_zishu["primaryReferenceImageId"] == second_image["id"]
        refreshed_batch_plan = client.post(
            f"/api/projects/{project['id']}/assets/batch-plan",
            json={"assetIds": [yun_zishu_id]},
        )
        assert refreshed_batch_plan.status_code == 200
        assert refreshed_batch_plan.json()["current"] is True
        assert refreshed_batch_plan.json()["costSampleCount"] == 2
        assert refreshed_batch_plan.json()["items"][0]["existingVersionCount"] == 2

        invalid_assets = json.loads(json.dumps(editable_assets, ensure_ascii=False))
        invalid_yun_zishu = next(
            item for item in invalid_assets["items"] if item["name"] == "云子姝"
        )
        invalid_yun_zishu["visualAnchor"] = ""
        rejected_assets = client.put(
            f"/api/projects/{project['id']}/assets", json=invalid_assets
        )
        assert rejected_assets.status_code == 422
        preserved_assets = client.get(
            f"/api/projects/{project['id']}/assets"
        ).json()
        assert next(
            item for item in preserved_assets["items"] if item["name"] == "云子姝"
        )["visualAnchor"] == "冷白肤色、素白中衣、长发凌乱、目光冷厉"

    database_bytes = (tmp_path / "mingyan.sqlite3").read_bytes()
    assert b"secret-not-for-sqlite" not in database_bytes
    assert b"image-secret-not-for-sqlite" not in database_bytes

    with TestClient(
        create_app(
            data_dir=tmp_path,
            static_dir=Path("missing"),
            credential_store=credentials,
        )
    ) as client:
        projects = client.get("/api/projects").json()
        assert len(projects) == 1
        assert projects[0]["name"] == "跨平台测试"
        assert projects[0]["stage"] == "assets"
        source = client.get(f"/api/projects/{projects[0]['id']}/source").json()
        assert source["title"] == "测试原文"
        assert source["chapterCount"] == 2
        analysis = client.get(f"/api/projects/{projects[0]['id']}/analysis").json()
        assert analysis["engine"] == "local-v1"
        assert len(analysis["plotNodes"]) == 2
        script_plan = client.get(f"/api/projects/{projects[0]['id']}/script-plan").json()
        assert script_plan["title"] == "凤掌九天"
        assert script_plan["sourceUpdatedAt"] == source["updatedAt"]
        screenplay = client.get(f"/api/projects/{projects[0]['id']}/screenplay").json()
        assert screenplay["episodeCount"] == 2
        assert screenplay["sourceUpdatedAt"] == source["updatedAt"]
        assert screenplay["planUpdatedAt"] == script_plan["updatedAt"]
        assert screenplay["status"] == "approved"
        assert screenplay["approvedAt"] is not None
        storyboards = client.get(
            f"/api/projects/{projects[0]['id']}/storyboards"
        ).json()
        assert len(storyboards) == 1
        assert storyboards[0]["groups"][0]["segments"][0]["camera"].startswith("Medium")
        assets = client.get(f"/api/projects/{projects[0]['id']}/assets").json()
        restored_yun_zishu = next(
            item for item in assets["items"] if item["name"] == "云子姝"
        )
        assert restored_yun_zishu["status"] == "confirmed"
        assert len(restored_yun_zishu["referenceImages"]) == 2
        assert restored_yun_zishu["primaryReferenceImageId"] == second_image["id"]
        assert client.get(restored_yun_zishu["referenceImages"][0]["url"]).status_code == 200
        restored_tasks = client.get(f"/api/projects/{projects[0]['id']}/tasks").json()
        assert len(restored_tasks) == 2
        assert all(task["status"] == "completed" for task in restored_tasks)
        restored_batch_plan = client.get(
            f"/api/projects/{projects[0]['id']}/assets/batch-plan"
        ).json()
        assert restored_batch_plan["current"] is True
        assert restored_batch_plan["items"][0]["name"] == "云子姝"
        settings = client.get("/api/settings/text-model").json()
        assert settings["configured"] is True
        assert settings["model"] == "example-chat"
        image_settings = client.get("/api/settings/image-model").json()
        assert image_settings["configured"] is True
        assert image_settings["model"] == "tt-image-2.5"


def test_asset_generation_queue_retries_and_resumes(tmp_path: Path) -> None:
    credentials = MemoryCredentialStore()
    created_prompts: list[str] = []
    retry_enabled = False

    def model_handler(request: httpx.Request) -> httpx.Response:
        nonlocal retry_enabled
        if request.url.host == "cdn.example.com":
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\n",
                headers={"content-type": "image/png"},
            )
        if request.url.path == "/v1/media/generate":
            payload = json.loads(request.content)
            created_prompts.append(payload["prompt"])
            return httpx.Response(
                200,
                json={"data": {"task_id": f"queue-task-{len(created_prompts)}"}},
            )
        if request.url.path == "/v1/media/status":
            task_id = request.url.params["task_id"]
            if task_id == "queue-task-2" and not retry_enabled:
                return httpx.Response(
                    200,
                    json={
                        "task_id": task_id,
                        "state": "failed",
                        "is_final": True,
                        "result_url": "",
                        "error": "模拟第二项失败",
                        "cost": 0,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "task_id": task_id,
                    "state": "success",
                    "is_final": True,
                    "result_url": f"https://cdn.example.com/{task_id}.png",
                    "error": "",
                    "cost": 0.12,
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    transport = httpx.MockTransport(model_handler)
    first_asset_id = "00000000-0000-4000-8000-000000000001"
    second_asset_id = "00000000-0000-4000-8000-000000000002"
    with TestClient(
        create_app(
            data_dir=tmp_path,
            static_dir=Path("missing"),
            credential_store=credentials,
            model_transport=transport,
        )
    ) as client:
        client.put(
            "/api/settings/image-model",
            json={
                "baseUrl": "https://example.com/v1",
                "model": "tt-image-2.5",
                "apiKey": "queue-image-secret",
            },
        )
        project = client.post(
            "/api/projects", json={"name": "队列测试", "description": ""}
        ).json()
        now = "2026-11-04T00:00:00+00:00"
        assets = [
            {
                "id": first_asset_id,
                "kind": "character",
                "name": "角色甲",
                "status": "confirmed",
                "referencePrompt": "角色甲完整提示词",
                "promptStandardSignature": "live-action|auto|2026-11-04.8",
            },
            {
                "id": second_asset_id,
                "kind": "scene",
                "name": "场景乙",
                "status": "confirmed",
                "referencePrompt": "场景乙完整提示词",
                "promptStandardSignature": "live-action|auto|2026-11-04.8",
            },
        ]
        plan = {
            "items": [
                {
                    "assetId": first_asset_id,
                    "assetKind": "character",
                    "name": "角色甲",
                    "prompt": "角色甲完整提示词",
                    "aspectRatio": "9:16",
                    "existingVersionCount": 0,
                },
                {
                    "assetId": second_asset_id,
                    "assetKind": "scene",
                    "name": "场景乙",
                    "prompt": "场景乙完整提示词",
                    "aspectRatio": "16:9",
                    "existingVersionCount": 0,
                },
            ],
            "estimatedUnitCost": None,
            "estimatedTotalCost": None,
            "costSampleCount": 0,
            "assetLibraryUpdatedAt": now,
            "confirmedAt": now,
        }
        with sqlite3.connect(tmp_path / "mingyan.sqlite3") as connection:
            connection.execute(
                """
                INSERT INTO project_assets (
                    project_id, payload, screenplay_updated_at,
                    storyboard_updated_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?)
                """,
                (project["id"], json.dumps({"items": assets}), now, now),
            )
            connection.execute(
                "INSERT INTO asset_batch_plans (project_id, payload, updated_at) VALUES (?, ?, ?)",
                (project["id"], json.dumps(plan), now),
            )

        queued = client.post(f"/api/projects/{project['id']}/assets/batch-plan/queue")
        assert queued.status_code == 200
        assert [item["status"] for item in queued.json()] == ["queued", "queued"]
        assert created_prompts == ["角色甲完整提示词", "场景乙完整提示词"]

        tasks = client.get(f"/api/projects/{project['id']}/tasks").json()
        assert {task["status"] for task in tasks} == {"completed", "failed"}
        failed_task = next(task for task in tasks if task["status"] == "failed")
        assert failed_task["error"] == "模拟第二项失败"
        library = client.get(f"/api/projects/{project['id']}/assets").json()
        assert len(library["items"][0]["referenceImages"]) == 1
        assert library["items"][1]["referenceImages"] == []

        retry_enabled = True
        retried = client.post(
            f"/api/projects/{project['id']}/tasks/{failed_task['id']}/retry"
        )
        assert retried.status_code == 200
        tasks = client.get(f"/api/projects/{project['id']}/tasks").json()
        retried_task = next(task for task in tasks if task["id"] == failed_task["id"])
        assert retried_task["status"] == "completed"
        assert retried_task["attemptCount"] == 2
        library = client.get(f"/api/projects/{project['id']}/assets").json()
        assert [len(item["referenceImages"]) for item in library["items"]] == [1, 1]

    interrupted_job_id = "00000000-0000-4000-8000-000000000003"
    with sqlite3.connect(tmp_path / "mingyan.sqlite3") as connection:
        connection.execute(
            """
            INSERT INTO asset_generation_jobs (
                id, project_id, batch_id, asset_id, asset_kind, title,
                prompt, aspect_ratio, model, status, provider_task_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'character', '角色甲参考图 V2', ?, '3:4',
                      'tt-image-2.5', 'running', 'provider-task-existing', ?, ?)
            """,
            (
                interrupted_job_id,
                project["id"],
                "00000000-0000-4000-8000-000000000004",
                first_asset_id,
                "角色甲完整提示词",
                now,
                now,
            ),
        )

    create_count_before_resume = len(created_prompts)
    with TestClient(
        create_app(
            data_dir=tmp_path,
            static_dir=Path("missing"),
            credential_store=credentials,
            model_transport=transport,
        )
    ) as client:
        interrupted = next(
            task
            for task in client.get(f"/api/projects/{project['id']}/tasks").json()
            if task["id"] == interrupted_job_id
        )
        assert interrupted["status"] == "interrupted"
        resumed = client.post(f"/api/projects/{project['id']}/tasks/resume")
        assert resumed.status_code == 200
        assert len(created_prompts) == create_count_before_resume
        resumed_task = next(
            task
            for task in client.get(f"/api/projects/{project['id']}/tasks").json()
            if task["id"] == interrupted_job_id
        )
        assert resumed_task["status"] == "completed"
        assert resumed_task["providerTaskId"] == "provider-task-existing"
        library = client.get(f"/api/projects/{project['id']}/assets").json()
        assert [len(item["referenceImages"]) for item in library["items"]] == [2, 1]
