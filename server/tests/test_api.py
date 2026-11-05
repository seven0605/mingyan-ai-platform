from pathlib import Path
import json
import sqlite3

import httpx
from fastapi.testclient import TestClient

from server.app import (
    VideoProductionPlanItem,
    apply_h3_continuity_override,
    asset_aspect_ratio,
    build_video_batch_prompt,
    comfyui_history_error,
    create_app,
    enforce_h3_axis_continuity,
    extract_h3_literal_locks,
    fit_h3_references,
    h3_authoritative_source,
    h3_shot_density_valid,
    is_collective_character,
    pack_video_plan_items,
)
from server.asset_tunnel import AssetTunnelStatus, TemporaryAssetTunnel
from server.storyboard_generation import build_storyboard_messages


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


class FakeAssetTunnel:
    def __init__(self) -> None:
        self.project_id: str | None = None
        self.running = False
        self.start_count = 0
        self.verify_count = 0

    def cloudflared_path(self) -> Path:
        return Path("/fake/cloudflared")

    def status(self) -> AssetTunnelStatus:
        return AssetTunnelStatus(
            installed=True,
            running=self.running,
            project_id=self.project_id if self.running else None,
            public_url="https://assets.example.com" if self.running else None,
            exposed_asset_count=1 if self.running else 0,
            error="",
        )

    def start(self, project_id: str, files: dict[str, Path]) -> dict[str, str]:
        assert files
        self.project_id = project_id
        self.running = True
        self.start_count += 1
        return {
            logical_id: f"https://assets.example.com/{self.start_count}/{logical_id}.png"
            for logical_id in files
        }

    def stop(self) -> None:
        self.running = False
        self.project_id = None

    def verify_urls(self, urls: dict[str, str]) -> None:
        assert urls
        assert all(url.startswith("https://") for url in urls.values())
        self.verify_count += 1

    def served_request_count(self) -> int:
        return 1


def test_storyboard_prompt_contains_live_action_v5_rules() -> None:
    messages = build_storyboard_messages(
        {"episodeNumber": 2},
        [{"index": 1}],
        "MiniMax H3",
        "16:9",
        24,
    )
    system_prompt = messages[0]["content"]
    assert "5—7个微镜头" in system_prompt
    assert "FACS可见动作" in system_prompt
    assert "同一角色的服装描述跨组必须逐字一致" in system_prompt
    assert "无背景音乐、无BGM、无配乐" in system_prompt


def test_collective_characters_use_widescreen() -> None:
    assert is_collective_character("character", "萧府护卫们") is True
    assert is_collective_character("character", "暗影卫众") is True
    assert is_collective_character("character", "云子姝") is False
    assert asset_aspect_ratio("live-action", "character", "萧府护卫们") == "16:9"
    assert asset_aspect_ratio("live-action", "character", "云子姝") == "9:16"


def test_video_plan_items_pack_into_thirty_second_requests() -> None:
    def item(index: int, duration: int) -> VideoProductionPlanItem:
        return VideoProductionPlanItem(
            id=f"e1-g{index}",
            episodeNumber=1,
            episodeTitle="测试集",
            groupIndex=index,
            sceneIndex=1,
            durationSeconds=duration,
            aspectRatio="16:9",
            targetModel="seedance-2.0",
            purpose=f"推进第{index}段",
            prompt=f"第{index}段提示词",
            assetReferences=[],
            blockingReasons=[],
            ready=True,
        )

    batches = pack_video_plan_items([item(1, 15), item(2, 15), item(3, 15)])
    assert [[part.id for part in batch] for batch in batches] == [
        ["e1-g1", "e1-g2"],
        ["e1-g3"],
    ]
    assert len(pack_video_plan_items([item(1, 15), item(3, 15)])) == 2
    padded_prompt = build_video_batch_prompt([item(1, 15)])
    assert "【00-15秒｜第1集·镜头组1】" in padded_prompt
    assert "【15-30秒｜自然收束】" in padded_prompt
    h3_batches = pack_video_plan_items(
        [item(1, 15), item(2, 15)], request_seconds=15
    )
    assert [[part.id for part in batch] for batch in h3_batches] == [
        ["e1-g1"],
        ["e1-g2"],
    ]
    h3_prompt = build_video_batch_prompt(
        [item(1, 15)], request_seconds=15, model_name="MiniMax H3"
    )
    assert "【任务参数】MiniMax H3，15秒" in h3_prompt
    assert "15-30秒" not in h3_prompt


def test_h3_reference_slots_prioritize_distinct_state_images_and_pad() -> None:
    references = [
        {"logicalId": "identity:a", "role": "identity", "name": "甲"},
        {"logicalId": "state:a", "role": "state", "name": "甲"},
        {"logicalId": "identity:b", "role": "identity", "name": "乙"},
        {"logicalId": "state:b", "role": "state", "name": "乙"},
        {"logicalId": "state:c", "role": "state", "name": "场景"},
    ]
    selected = fit_h3_references(references, 4)
    assert [item["logicalId"] for item in selected] == [
        "state:a",
        "state:b",
        "state:c",
        "identity:a",
    ]
    padded = fit_h3_references([references[1]], 2)
    assert padded[0]["logicalId"] == "state:a"
    assert padded[1]["logicalId"] == "state:a:repeat-2"
    prioritized = fit_h3_references(references, 2, "乙走向场景")
    assert [item["logicalId"] for item in prioritized] == ["state:b", "state:c"]
    continuity = {"logicalId": "continuity:g1", "role": "continuity", "name": "终帧"}
    continued = fit_h3_references([*references, continuity], 4)
    assert [item["logicalId"] for item in continued] == [
        "continuity:g1",
        "state:a",
        "state:b",
        "state:c",
    ]


def test_comfyui_history_error_detects_failed_incomplete_job() -> None:
    status = {
        "status_str": "error",
        "completed": False,
        "messages": [
            [
                "execution_error",
                {"exception_message": "Allocation failed: out of memory\ntraceback"},
            ]
        ],
    }
    assert comfyui_history_error(status) == "H3 工作流执行失败：云端 GPU 显存不足"


def test_h3_continuity_override_makes_picture_pixels_authoritative() -> None:
    prompt = "detailed_description:\n[Shot 1] The subject raises her arm."
    continued = apply_h3_continuity_override(prompt, True)
    assert "literal pixels of <Picture 1>" in continued
    assert "same shot for 0.8-1.0 seconds" in continued
    assert "Never use a one-frame flash" in continued
    assert "[Shot 1] The subject raises her arm." not in continued
    assert apply_h3_continuity_override(prompt, False) == prompt


def test_h3_literal_locks_keep_exact_outfit_wording() -> None:
    locks = extract_h3_literal_locks(
        [
            "【关键锁定】\n- 云子姝：粉桃短袄、浅青马面裙；禁止换装。\n"
            "- 萧云衡：淡藕灰锦袍；禁止换装或伤痕消失。",
            "- 云子姝：粉桃短袄、浅青马面裙；禁止换装。",
        ]
    )
    assert locks == [
        "云子姝：粉桃短袄、浅青马面裙；禁止换装。",
        "萧云衡：淡藕灰锦袍；禁止换装或伤痕消失。",
    ]


def test_h3_axis_continuity_removes_cross_axis_language() -> None:
    prompt = (
        "[Shot 2] cutting across the 180-degree axis line by 50 degrees. "
        "[Shot 3] crossing the 180-degree axis."
    )
    fixed = enforce_h3_axis_continuity(prompt)
    assert "across the 180-degree axis" not in fixed
    assert "crossing the 180-degree axis" not in fixed
    assert fixed.count("original side of the 180-degree axis") == 2
    assert "across the 180-degree axis" not in enforce_h3_axis_continuity(
        "[Shot 2] cut across the 180-degree axis to an over-the-shoulder shot."
    )


def test_h3_authoritative_source_drops_duplicate_storyboard_prose() -> None:
    prompt = (
        "【首帧锁定】旧的冗长说明\n【动作与表演节拍】重复内容\n"
        "【模型执行主提示词】[出镜角色-物品-场景]\n权威七模块执行稿"
    )
    assert h3_authoritative_source(prompt) == (
        "[出镜角色-物品-场景]\n权威七模块执行稿"
    )


def test_h3_shot_density_requires_five_to_seven_shots_for_fifteen_seconds() -> None:
    five_shots = "\n".join(f"[Shot {index}]" for index in range(1, 6))
    assert h3_shot_density_valid(five_shots, 15)
    assert not h3_shot_density_valid("[Shot 1]\n[Shot 2]\n[Shot 3]", 15)


def test_comfyui_h3_connector_runs_workflow_and_downloads_video(tmp_path: Path) -> None:
    credentials = MemoryCredentialStore()
    prompt_requests: list[dict] = []

    def comfyui_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {"comfyui_version": "0.30.0"}})
        if request.url.path == "/upload/image":
            assert b"mock-reference" in request.content
            return httpx.Response(
                200,
                json={"name": "mingyan-reference.png", "subfolder": "", "type": "input"},
            )
        if request.url.path == "/prompt":
            payload = json.loads(request.content)
            prompt_requests.append(payload)
            workflow = payload["prompt"]
            assert workflow["1"]["inputs"]["text"] == "H3 测试提示词"
            assert workflow["1"]["inputs"]["seconds"] == 15
            assert workflow["1"]["inputs"]["width"] == 1280
            assert workflow["2"]["inputs"]["image"] == "mingyan-reference.png"
            return httpx.Response(200, json={"prompt_id": "h3-task-1"})
        if request.url.path == "/history/h3-task-1":
            return httpx.Response(
                200,
                json={
                    "h3-task-1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "3": {
                                "gifs": [
                                    {
                                        "filename": "h3-output.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        if request.url.path == "/view":
            assert request.url.params["filename"] == "h3-output.mp4"
            return httpx.Response(
                200,
                content=b"mock-h3-mp4",
                headers={"content-type": "video/mp4"},
            )
        return httpx.Response(404)

    workflow = {
        "1": {
            "class_type": "H3Prompt",
            "inputs": {
                "text": "{{prompt}}",
                "seconds": "{{seconds}}",
                "width": "{{width}}",
                "height": "{{height}}",
                "seed": "{{seed}}",
            },
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": "{{reference_1}}"},
        },
        "3": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "h3"}},
    }
    with TestClient(
        create_app(
            data_dir=tmp_path,
            static_dir=Path("missing"),
            credential_store=credentials,
            model_transport=httpx.MockTransport(comfyui_handler),
        )
    ) as client:
        saved = client.put(
            "/api/settings/comfyui-video",
            json={
                "baseUrl": "https://h3.example.com/",
                "workflowName": "H3 15秒测试工作流",
                "workflowJson": json.dumps(workflow),
                "allowInsecureTls": True,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["configured"] is True
        assert saved.json()["workflowConfigured"] is True
        assert saved.json()["allowInsecureTls"] is True
        tested = client.post("/api/settings/comfyui-video/test")
        assert tested.status_code == 200
        assert tested.json()["model"] == "MiniMax H3"
        selected = client.put(
            "/api/settings/video-backend", json={"activeBackend": "comfyui"}
        )
        assert selected.status_code == 200
        assert selected.json()["configured"] is True

        project = client.post(
            "/api/projects", json={"name": "H3测试", "description": ""}
        ).json()
        asset_id = "11111111-1111-4111-8111-111111111111"
        image_id = "22222222-2222-4222-8222-222222222222"
        image_dir = tmp_path / "generated" / project["id"] / asset_id
        image_dir.mkdir(parents=True)
        (image_dir / f"{image_id}.png").write_bytes(b"mock-reference")
        job_id = "33333333-3333-4333-8333-333333333333"
        now = "2026-11-05T00:00:00+00:00"
        with sqlite3.connect(tmp_path / "mingyan.sqlite3") as connection:
            connection.execute(
                """
                INSERT INTO video_generation_jobs (
                    id, project_id, batch_id, plan_item_id, title, prompt,
                    seconds, aspect_ratio, reference_assets, model, backend,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'interrupted', ?, ?)
                """,
                (
                    job_id,
                    project["id"],
                    "h3-batch",
                    "e1-g1",
                    "H3测试视频",
                    "H3 测试提示词",
                    15,
                    "16:9",
                    json.dumps(
                        [
                            {
                                "logicalId": "asset:image",
                                "assetId": asset_id,
                                "imageId": image_id,
                                "name": "测试角色",
                                "role": "state",
                                "itemIds": ["e1-g1"],
                            }
                        ]
                    ),
                    "MiniMax H3",
                    "comfyui",
                    now,
                    now,
                ),
            )

        resumed = client.post(f"/api/projects/{project['id']}/tasks/resume")
        assert resumed.status_code == 200
        tasks = client.get(f"/api/projects/{project['id']}/tasks").json()
        completed = next(task for task in tasks if task["id"] == job_id)
        assert completed["status"] == "completed"
        assert completed["providerTaskId"] == "h3-task-1"
        video = client.get(completed["resultUrl"])
        assert video.status_code == 200
        assert video.content == b"mock-h3-mp4"
        assert len(prompt_requests) == 1


def test_temporary_asset_gateway_only_serves_whitelisted_files(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed.png"
    allowed.write_bytes(b"\x89PNG\r\n\x1a\npublic-test")
    hidden = tmp_path / "hidden.png"
    hidden.write_bytes(b"\x89PNG\r\n\x1a\nhidden-test")
    tunnel = TemporaryAssetTunnel(tmp_path)
    urls = tunnel.start_local("project-1", {"allowed": allowed})
    try:
        response = httpx.get(urls["allowed"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.content.endswith(b"public-test")
        assert httpx.head(urls["allowed"]).status_code == 200
        tunnel.verify_urls(urls, timeout_seconds=1)
        assert tunnel.served_request_count() == 3
        local_root = urls["allowed"].split("/media/", 1)[0]
        assert httpx.get(f"{local_root}/api/projects").status_code == 404
        assert httpx.get(f"{local_root}/media/wrong-token/hidden.png").status_code == 404
    finally:
        tunnel.stop()


def test_project_lifecycle_persists(tmp_path: Path) -> None:
    credentials = MemoryCredentialStore()
    invalid_screenplay = False
    invalid_storyboard = False
    image_generation_failed = False
    image_requests: list[dict] = []
    video_requests: list[dict] = []
    fake_tunnel = FakeAssetTunnel()

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
            assert any(name in request_payload["prompt"] for name in ("云子姝", "萧云衡"))
            assert request_payload["params"]["aspect_ratio"] == "9:16"
            assert request_payload["params"]["resolution"] == "1K"
            yun_request_count = sum(
                "云子姝" in item["prompt"] for item in image_requests
            )
            if "萧云衡" in request_payload["prompt"] or yun_request_count == 1:
                assert "images" not in request_payload["params"]
            else:
                assert request_payload["params"]["images"][0].startswith(
                    "data:image/png;base64,"
                )
                assert "单一身份母版硬锁" in request_payload["prompt"]
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
        if request.url.path == "/v1/videos":
            assert request.headers["Authorization"] == "Bearer video-secret-not-for-sqlite"
            request_payload = json.loads(request.content)
            video_requests.append(request_payload)
            assert request_payload["model"] == "BD Seedance2.5"
            assert "【参考图顺序锁定】图1=" in request_payload["prompt"]
            assert request_payload["seconds"] == "30"
            assert "【00-15秒｜第1集·镜头组1】" in request_payload["prompt"]
            assert "【15-30秒｜第1集·镜头组2】" in request_payload["prompt"]
            assert "【全局连续性硬锁】" in request_payload["prompt"]
            assert "【首帧锁定】" in request_payload["prompt"]
            assert "镜头节拍 1" in request_payload["prompt"]
            assert "用于e1-g1" in request_payload["prompt"]
            assert "用于e1-g2" in request_payload["prompt"]
            assert "同名人物跨镜头组必须保持同一身份" in request_payload["prompt"]
            assert "身份母版为最高优先级" in request_payload["prompt"]
            assert "服装、发型、身体状态与情绪" in request_payload["prompt"]
            assert request_payload["size"] == "1280x720"
            reference_urls = request_payload["metadata"]["__workbench_refs"][
                "reference_image_urls"
            ]
            assert len(reference_urls) >= 3
            assert all(
                url.startswith("https://assets.example.com/")
                for url in reference_urls
            )
            assert any(generated_image["id"] in url for url in reference_urls)
            assert any(second_image["id"] in url for url in reference_urls)
            return httpx.Response(
                200, json={"id": f"video-task-{len(video_requests)}"}
            )
        if request.url.path.endswith("/content") and request.url.path.startswith(
            "/v1/videos/"
        ):
            assert request.headers["Authorization"] == "Bearer video-secret-not-for-sqlite"
            return httpx.Response(
                200,
                content=b"mock-mp4-content",
                headers={"content-type": "video/mp4"},
            )
        if request.url.path.startswith("/v1/videos/"):
            assert request.headers["Authorization"] == "Bearer video-secret-not-for-sqlite"
            return httpx.Response(
                200,
                json={
                    "id": request.url.path.rsplit("/", 1)[-1],
                    "status": "completed",
                    "cost": 6.9,
                },
            )
        if request.url.path == "/v1/models":
            assert request.headers["Authorization"] in {
                "Bearer secret-not-for-sqlite",
                "Bearer image-secret-not-for-sqlite",
                "Bearer video-secret-not-for-sqlite",
            }
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "example-chat"},
                        {"id": "tt-image-2.5"},
                        {"id": "BD Seedance2.5"},
                    ]
                },
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
            asset_tunnel_service=fake_tunnel,
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

        empty_video_settings = client.get("/api/settings/video-model")
        assert empty_video_settings.status_code == 200
        assert empty_video_settings.json()["configured"] is False

        configured_video = client.put(
            "/api/settings/video-model",
            json={
                "baseUrl": "https://shuikule.top/v1/",
                "model": "BD Seedance2.5",
                "apiKey": "video-secret-not-for-sqlite",
            },
        )
        assert configured_video.status_code == 200
        assert configured_video.json() == {
            "provider": "shuikule-openai-compatible",
            "baseUrl": "https://shuikule.top/v1",
            "model": "BD Seedance2.5",
            "hasCredential": True,
            "configured": True,
            "updatedAt": configured_video.json()["updatedAt"],
        }
        assert "apiKey" not in configured_video.json()
        assert credentials.values["video-model-api-key"] == "video-secret-not-for-sqlite"

        video_connection = client.post("/api/settings/video-model/test")
        assert video_connection.status_code == 200
        assert video_connection.json()["connected"] is True
        assert video_connection.json()["model"] == "BD Seedance2.5"
        assert "未生成视频" in video_connection.json()["message"]

        tunnel_status = client.get("/api/settings/asset-tunnel")
        assert tunnel_status.status_code == 200
        assert tunnel_status.json()["provider"] == "cloudflare-quick-tunnel"
        assert tunnel_status.json()["running"] is False
        assert tunnel_status.json()["publicUrl"] is None
        assert tunnel_status.json()["exposedAssetCount"] == 0

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

        blocked_followup = client.post(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images"
        )
        assert blocked_followup.status_code == 409
        assert "剧情状态图" in blocked_followup.json()["detail"]
        identity_master_result = client.post(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/identity-masters",
            json={
                "sourceImageId": generated_image["id"],
                "imageData": "data:image/png;base64,iVBORw0KGgo=",
            },
        )
        assert identity_master_result.status_code == 200
        identity_yun_zishu = next(
            item
            for item in identity_master_result.json()["items"]
            if item["name"] == "云子姝"
        )
        identity_master = identity_yun_zishu["identityMasters"][0]
        assert identity_yun_zishu["identityMasterId"] == identity_master["id"]
        assert identity_master["sourceImageId"] == generated_image["id"]
        assert client.get(identity_master["url"]).content.startswith(b"\x89PNG")

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
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images",
            json={
                "mode": "state",
                "stateLabel": "失败状态测试",
                "statePrompt": "素白寝衣、长发披散",
            },
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
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images",
            json={
                "mode": "state",
                "stateLabel": "寝衣重生状态",
                "statePrompt": "素白寝衣、长发凌乱、病后虚弱、眼神冷冽",
            },
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
        assert second_image["identityReferenceImageId"] == identity_master["id"]
        assert second_image["role"] == "state"
        assert second_image["stateLabel"] == "寝衣重生状态"
        assert "单一身份母版硬锁" in second_image["prompt"]
        assert "不得输出四宫格" in second_image["prompt"]
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

        video_assets = client.get(f"/api/projects/{project['id']}/assets").json()
        xiao_yunheng = next(
            item for item in video_assets["items"] if item["name"] == "萧云衡"
        )
        xiao_yunheng["status"] = "confirmed"
        xiao_yunheng["description"] = "身着玄色将军服的青年将军"
        xiao_yunheng["visualAnchor"] = "冷峻面容、玄色将军服、束发金冠"
        xiao_yunheng["continuityNotes"] = "脸型、五官、服装纹样保持一致"
        xiao_yunheng["referencePrompt"] = "【角色资产卡｜萧云衡】完整提示词"
        xiao_yunheng["promptStandardSignature"] = (
            "handpainted-3d2d|ming|2026-11-04.8"
        )
        saved_video_assets = client.put(
            f"/api/projects/{project['id']}/assets",
            json={
                "items": video_assets["items"],
                "standard": video_assets["standard"],
            },
        )
        assert saved_video_assets.status_code == 200
        generated_xiao_result = client.post(
            f"/api/projects/{project['id']}/assets/{xiao_yunheng_id}/images"
        )
        assert generated_xiao_result.status_code == 200
        generated_xiao = next(
            item
            for item in generated_xiao_result.json()["items"]
            if item["name"] == "萧云衡"
        )
        xiao_image = generated_xiao["referenceImages"][0]
        xiao_master_result = client.post(
            f"/api/projects/{project['id']}/assets/{xiao_yunheng_id}/identity-masters",
            json={
                "sourceImageId": xiao_image["id"],
                "imageData": "data:image/png;base64,iVBORw0KGgo=",
            },
        )
        assert xiao_master_result.status_code == 200
        xiao_master = next(
            item
            for item in xiao_master_result.json()["items"]
            if item["name"] == "萧云衡"
        )["identityMasters"][0]

        video_plan = client.get(f"/api/projects/{project['id']}/video-plan")
        assert video_plan.status_code == 200
        assert len(video_plan.json()["items"]) == 8
        assert all(item["ready"] for item in video_plan.json()["items"])
        assert all(
            len(item["assetReferences"]) >= 2
            for item in video_plan.json()["items"]
        )
        selected_video_ids = [item["id"] for item in video_plan.json()["items"][:2]]
        first_yun_reference = next(
            reference
            for reference in video_plan.json()["items"][0]["assetReferences"]
            if reference["assetId"] == yun_zishu_id
        )
        assert len(first_yun_reference["availableImages"]) == 2
        assert first_yun_reference["availableImages"][0]["identityMasterId"] == (
            identity_master["id"]
        )
        first_xiao_reference = next(
            reference
            for reference in video_plan.json()["items"][0]["assetReferences"]
            if reference["assetId"] == xiao_yunheng_id
        )
        assert first_xiao_reference["identityMasterId"] == xiao_master["id"]
        reference_image_ids = {
            selected_video_ids[0]: {yun_zishu_id: generated_image["id"]},
            selected_video_ids[1]: {yun_zishu_id: second_image["id"]},
        }
        confirmed_video_plan = client.post(
            f"/api/projects/{project['id']}/video-plan",
            json={
                "itemIds": selected_video_ids,
                "referenceImageIds": reference_image_ids,
            },
        )
        assert confirmed_video_plan.status_code == 200
        assert confirmed_video_plan.json()["current"] is True
        assert confirmed_video_plan.json()["selectedItemIds"] == selected_video_ids
        assert confirmed_video_plan.json()["referenceImageIds"] == reference_image_ids
        confirmed_items = confirmed_video_plan.json()["items"]
        assert next(
            reference
            for reference in confirmed_items[0]["assetReferences"]
            if reference["assetId"] == yun_zishu_id
        )["imageId"] == generated_image["id"]
        assert next(
            reference
            for reference in confirmed_items[1]["assetReferences"]
            if reference["assetId"] == yun_zishu_id
        )["imageId"] == second_image["id"]
        assert client.get("/api/projects").json()[0]["stage"] == "video"
        queued_videos = client.post(
            f"/api/projects/{project['id']}/video-plan/queue"
        )
        assert queued_videos.status_code == 200
        assert [task["type"] for task in queued_videos.json()] == ["video"]
        assert [task["status"] for task in queued_videos.json()] == ["queued"]
        assert queued_videos.json()[0]["title"].endswith("镜头组 1–2（30秒）")
        assert len(video_requests) == 1
        assert fake_tunnel.start_count == 1
        assert fake_tunnel.verify_count == 1
        assert fake_tunnel.running is False
        video_tasks = [
            task
            for task in client.get(f"/api/projects/{project['id']}/tasks").json()
            if task["type"] == "video"
        ]
        assert len(video_tasks) == 1
        assert all(task["status"] == "completed" for task in video_tasks)
        assert all(task["providerTaskId"].startswith("video-task-") for task in video_tasks)
        generated_video = client.get(video_tasks[0]["resultUrl"])
        assert generated_video.status_code == 200
        assert generated_video.headers["content-type"] == "video/mp4"
        assert generated_video.content == b"mock-mp4-content"

        assert client.put(
            f"/api/projects/{project['id']}/assets/{yun_zishu_id}/images/{generated_image['id']}/primary"
        ).status_code == 200
        assert client.get(f"/api/projects/{project['id']}/video-plan").json()[
            "current"
        ] is False

    database_bytes = (tmp_path / "mingyan.sqlite3").read_bytes()
    assert b"secret-not-for-sqlite" not in database_bytes
    assert b"image-secret-not-for-sqlite" not in database_bytes
    assert b"video-secret-not-for-sqlite" not in database_bytes

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
        assert projects[0]["stage"] == "video"
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
        assert restored_yun_zishu["primaryReferenceImageId"] == generated_image["id"]
        assert client.get(restored_yun_zishu["referenceImages"][0]["url"]).status_code == 200
        restored_tasks = client.get(f"/api/projects/{projects[0]['id']}/tasks").json()
        assert len(restored_tasks) == 4
        assert all(task["status"] == "completed" for task in restored_tasks)
        restored_batch_plan = client.get(
            f"/api/projects/{projects[0]['id']}/assets/batch-plan"
        ).json()
        assert restored_batch_plan["current"] is False
        assert restored_batch_plan["items"][0]["name"] == "云子姝"
        restored_video_plan = client.get(
            f"/api/projects/{projects[0]['id']}/video-plan"
        ).json()
        assert restored_video_plan["selectedItemIds"] == selected_video_ids
        assert restored_video_plan["referenceImageIds"] == reference_image_ids
        assert restored_video_plan["current"] is False
        settings = client.get("/api/settings/text-model").json()
        assert settings["configured"] is True
        assert settings["model"] == "example-chat"
        image_settings = client.get("/api/settings/image-model").json()
        assert image_settings["configured"] is True
        assert image_settings["model"] == "tt-image-2.5"
        video_settings = client.get("/api/settings/video-model").json()
        assert video_settings["configured"] is True
        assert video_settings["model"] == "BD Seedance2.5"


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
