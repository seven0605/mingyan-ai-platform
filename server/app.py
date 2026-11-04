from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from keyring.errors import KeyringError
from fastapi.staticfiles import StaticFiles
from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from server.credential_store import CredentialStore, SystemCredentialStore
from server.script_planning import build_script_messages, extract_json_object
from server.screenplay_generation import (
    build_screenplay_episode_messages,
    build_screenplay_refinement_messages,
)
from server.story_analysis import analyze_story
from server.storyboard_generation import build_storyboard_messages

ProjectStage = Literal["text", "script", "storyboard", "assets", "video"]
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
SourceTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
SourceContent = Annotated[str, StringConstraints(min_length=1, max_length=5_000_000)]
CHAPTER_HEADING = re.compile(
    r"^(?:第[0-9０-９一二三四五六七八九十百千万]{1,16}[章节回卷部]|楔子|序章|番外)\s*$",
    re.MULTILINE,
)


class ProjectCreate(BaseModel):
    name: ProjectName
    description: str = ""


class ProjectStageUpdate(BaseModel):
    stage: ProjectStage


class SourceUpsert(BaseModel):
    title: SourceTitle
    content: SourceContent


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    stage: ProjectStage
    createdAt: str
    updatedAt: str


class SourceOut(BaseModel):
    projectId: str
    title: str
    content: str
    charCount: int
    chapterCount: int
    updatedAt: str


class AnalysisCandidate(BaseModel):
    name: str
    mentions: int
    chapters: list[int]


class PlotNode(BaseModel):
    index: int
    title: str
    charCount: int
    opening: str
    closing: str


class StoryAnalysisOut(BaseModel):
    projectId: str
    engine: str
    sourceUpdatedAt: str
    updatedAt: str
    characters: list[AnalysisCandidate]
    scenes: list[AnalysisCandidate]
    plotNodes: list[PlotNode]


class TextModelSettingsUpdate(BaseModel):
    baseUrl: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    apiKey: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None

    @field_validator("baseUrl")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("接口地址必须是有效的 http 或 https 地址")
        return value.rstrip("/")


class TextModelSettingsOut(BaseModel):
    provider: Literal["openai-compatible"]
    baseUrl: str
    model: str
    hasCredential: bool
    configured: bool
    updatedAt: str | None


class TextModelConnectionOut(BaseModel):
    connected: bool
    model: str
    latencyMs: int
    message: str


class ImageModelSettingsUpdate(TextModelSettingsUpdate):
    pass


class ImageModelSettingsOut(BaseModel):
    provider: Literal["buming-openai-compatible"]
    baseUrl: str
    model: str
    hasCredential: bool
    configured: bool
    updatedAt: str | None


class ScriptCharacter(BaseModel):
    name: str
    identity: str
    goal: str
    obstacle: str
    arc: str


class ScriptRelationship(BaseModel):
    fromCharacter: str
    toCharacter: str
    publicRelation: str
    trueAttitude: str
    tension: str


class ScriptScene(BaseModel):
    index: int
    chapter: str
    heading: str
    characters: list[str]
    objective: str
    conflict: str
    turn: str
    outcome: str


class ScriptPlanPayload(BaseModel):
    title: str
    format: str
    logline: str
    coreConflict: str
    characters: list[ScriptCharacter]
    relationships: list[ScriptRelationship]
    scenes: list[ScriptScene]
    adaptationNotes: list[str]


class ScriptPlanOut(ScriptPlanPayload):
    projectId: str
    model: str
    sourceUpdatedAt: str
    updatedAt: str


class ScreenplayGenerateRequest(BaseModel):
    adaptationMode: Literal["faithful", "commercial"]
    targetSeconds: Literal[60, 90, 120, 180]
    episodeCount: int

    @field_validator("episodeCount")
    @classmethod
    def validate_episode_count(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("分集数必须在 1 到 5 之间")
        return value


class ScreenplayBeat(BaseModel):
    kind: Literal["action", "dialogue", "voiceover"]
    speaker: str
    text: str
    sourceRef: str
    origin: Literal["source", "translation", "suggestion"]
    estimatedSeconds: int


class ScreenplayScene(BaseModel):
    index: int
    heading: str
    characters: list[str]
    props: list[str]
    objective: str
    obstacle: str
    estimatedSeconds: int
    sourceRefs: list[str]
    beats: list[ScreenplayBeat]
    result: str


class ScreenplayEpisode(BaseModel):
    episodeNumber: int
    title: str
    sourceRange: str
    objective: str
    centralConflict: str
    stateChange: str
    targetSeconds: int
    estimatedSeconds: int
    scenes: list[ScreenplayScene]
    endingState: str
    hook: str
    qualityNotes: list[str]
    fidelityStatus: Literal["unchecked", "passed", "review"] = "unchecked"
    fidelityNotes: list[str] = Field(default_factory=list)


class ScreenplayRefinementResult(BaseModel):
    episode: ScreenplayEpisode
    fidelityStatus: Literal["passed", "review"] = "review"
    fidelityNotes: list[str] = Field(default_factory=list)
    revisionNotes: list[str] = Field(default_factory=list)


class ScreenplayPayload(BaseModel):
    adaptationMode: Literal["faithful", "commercial"]
    targetSeconds: int
    episodeCount: int
    episodes: list[ScreenplayEpisode]
    continuityNotes: list[str]


class ScreenplayOut(ScreenplayPayload):
    projectId: str
    model: str
    sourceUpdatedAt: str
    planUpdatedAt: str
    updatedAt: str
    status: Literal["draft", "approved"]
    approvedAt: str | None


class StoryboardGenerateRequest(BaseModel):
    targetModel: Literal["seedance-2.0", "sora-2", "kling-3.0", "veo-3.1"] = "seedance-2.0"
    aspectRatio: Literal["16:9", "9:16"] = "16:9"


class StoryboardSegment(BaseModel):
    startSeconds: float
    endSeconds: float
    camera: str
    action: str
    motionVisual: str
    expression: str
    environment: str
    effects: str
    sound: str


class StoryboardGroup(BaseModel):
    index: int
    sceneIndex: int
    startSeconds: float
    endSeconds: float
    durationSeconds: float
    purpose: str
    hookType: str
    metadata: str
    sceneDescription: str
    firstFrameLock: str
    segments: list[StoryboardSegment]
    qualityBase: str
    visualStyle: str
    subjects: list[str]
    spatialRelations: str
    actionTimeline: str
    cameraLanguage: str
    emotionalTurn: str
    keyDialogue: str
    negativePrompt: str
    generationParams: str
    videoPrompt: str


class StoryboardPayload(BaseModel):
    episodeNumber: int
    episodeTitle: str
    styleBible: str
    groups: list[StoryboardGroup]
    continuityNotes: list[str]


class StoryboardOut(StoryboardPayload):
    projectId: str
    model: str
    targetModel: str
    aspectRatio: str
    fps: int
    totalSeconds: int
    screenplayUpdatedAt: str
    updatedAt: str


class AssetImageVersion(BaseModel):
    id: str
    url: str
    prompt: str
    model: str
    taskId: str
    aspectRatio: str
    resolution: str
    cost: float | None = None
    createdAt: str


class AssetItem(BaseModel):
    id: str
    kind: Literal["character", "scene", "prop"]
    name: str
    status: Literal["draft", "confirmed"] = "draft"
    appearances: list[str] = Field(default_factory=list)
    sourceRefs: list[str] = Field(default_factory=list)
    description: str = ""
    visualAnchor: str = ""
    continuityNotes: str = ""
    referencePrompt: str = ""
    promptStandardSignature: str = ""
    referenceImages: list[AssetImageVersion] = Field(default_factory=list)
    primaryReferenceImageId: str | None = None

    @model_validator(mode="after")
    def validate_primary_reference_image(self) -> "AssetItem":
        image_ids = {image.id for image in self.referenceImages}
        if self.primaryReferenceImageId and self.primaryReferenceImageId not in image_ids:
            raise ValueError("主参考图必须来自当前资产的历史版本")
        if self.referenceImages and not self.primaryReferenceImageId:
            self.primaryReferenceImageId = self.referenceImages[0].id
        return self


class AssetStandardSettings(BaseModel):
    visualStandard: Literal[
        "live-action",
        "guofeng-3d",
        "handpainted-3d2d",
        "western-dark-medieval",
        "victorian-gothic",
    ] = "live-action"
    costumeEra: Literal[
        "auto",
        "xia",
        "shang",
        "zhou",
        "qin",
        "han",
        "three-kingdoms",
        "jin",
        "northern-southern",
        "sui",
        "tang",
        "five-dynasties",
        "song",
        "yuan",
        "ming",
        "qing",
    ] = "auto"


ASSET_PROMPT_TEMPLATE_VERSION = "2026-11-04.6"


def asset_standard_signature(settings: AssetStandardSettings) -> str:
    return (
        f"{settings.visualStandard}|{settings.costumeEra}|"
        f"{ASSET_PROMPT_TEMPLATE_VERSION}"
    )


def asset_aspect_ratio(
    standard: str, kind: Literal["character", "scene", "prop"]
) -> str:
    if standard == "western-dark-medieval":
        return "16:9"
    if standard in {"victorian-gothic", "guofeng-3d"}:
        return "9:16" if kind == "character" else "16:9"
    return "16:9" if kind == "scene" else "9:16"


class AssetLibraryPayload(BaseModel):
    standard: AssetStandardSettings = Field(default_factory=AssetStandardSettings)
    items: list[AssetItem]


class AssetLibraryOut(AssetLibraryPayload):
    projectId: str
    screenplayUpdatedAt: str
    storyboardUpdatedAt: str | None
    updatedAt: str


class AssetBatchPlanCreate(BaseModel):
    assetIds: list[str] = Field(min_length=1, max_length=100)

    @field_validator("assetIds")
    @classmethod
    def validate_asset_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("批量生产清单不能包含重复资产")
        return values


class AssetBatchPlanItem(BaseModel):
    assetId: str
    assetKind: Literal["character", "scene", "prop"]
    name: str
    prompt: str
    aspectRatio: str
    existingVersionCount: int


class AssetBatchPlanPayload(BaseModel):
    items: list[AssetBatchPlanItem]
    estimatedUnitCost: float | None = None
    estimatedTotalCost: float | None = None
    costSampleCount: int = 0
    assetLibraryUpdatedAt: str
    confirmedAt: str


class AssetBatchPlanOut(AssetBatchPlanPayload):
    projectId: str
    current: bool
    updatedAt: str


class ProjectTaskOut(BaseModel):
    id: str
    projectId: str
    type: Literal["asset-image"]
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    title: str
    assetId: str
    assetKind: Literal["character", "scene", "prop"]
    providerTaskId: str
    model: str
    resultUrl: str
    cost: float | None = None
    batchId: str = ""
    error: str = ""
    attemptCount: int = 1
    createdAt: str
    updatedAt: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_analyses (
                project_id TEXT PRIMARY KEY,
                engine TEXT NOT NULL,
                payload TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_sources (
                project_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                chapter_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS model_settings (
                kind TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_script_plans (
                project_id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                payload TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_screenplays (
                project_id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                payload TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                plan_updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                approved_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_storyboards (
                project_id TEXT NOT NULL,
                episode_number INTEGER NOT NULL,
                model TEXT NOT NULL,
                target_model TEXT NOT NULL,
                aspect_ratio TEXT NOT NULL,
                fps INTEGER NOT NULL,
                total_seconds INTEGER NOT NULL,
                payload TEXT NOT NULL,
                screenplay_updated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project_id, episode_number),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_assets (
                project_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                screenplay_updated_at TEXT NOT NULL,
                storyboard_updated_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_batch_plans (
                project_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_generation_jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                asset_kind TEXT NOT NULL,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                aspect_ratio TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_task_id TEXT NOT NULL DEFAULT '',
                result_url TEXT NOT NULL DEFAULT '',
                cost REAL,
                error TEXT NOT NULL DEFAULT '',
                attempt_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        screenplay_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(project_screenplays)").fetchall()
        }
        if "status" not in screenplay_columns:
            connection.execute(
                "ALTER TABLE project_screenplays ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'"
            )
        if "approved_at" not in screenplay_columns:
            connection.execute(
                "ALTER TABLE project_screenplays ADD COLUMN approved_at TEXT"
            )


def row_to_project(row: sqlite3.Row) -> ProjectOut:
    return ProjectOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        stage=row["stage"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def row_to_source(row: sqlite3.Row) -> SourceOut:
    return SourceOut(
        projectId=row["project_id"],
        title=row["title"],
        content=row["content"],
        charCount=row["char_count"],
        chapterCount=row["chapter_count"],
        updatedAt=row["updated_at"],
    )


def row_to_analysis(row: sqlite3.Row) -> StoryAnalysisOut:
    payload = json.loads(row["payload"])
    return StoryAnalysisOut(
        projectId=row["project_id"],
        engine=row["engine"],
        sourceUpdatedAt=row["source_updated_at"],
        updatedAt=row["updated_at"],
        **payload,
    )


def row_to_script_plan(row: sqlite3.Row) -> ScriptPlanOut:
    payload = json.loads(row["payload"])
    return ScriptPlanOut(
        projectId=row["project_id"],
        model=row["model"],
        sourceUpdatedAt=row["source_updated_at"],
        updatedAt=row["updated_at"],
        **payload,
    )


def row_to_screenplay(row: sqlite3.Row) -> ScreenplayOut:
    screenplay = ScreenplayPayload.model_validate(json.loads(row["payload"]))
    screenplay = apply_screenplay_quality_checks(normalize_screenplay_timing(screenplay))
    return ScreenplayOut(
        projectId=row["project_id"],
        model=row["model"],
        sourceUpdatedAt=row["source_updated_at"],
        planUpdatedAt=row["plan_updated_at"],
        updatedAt=row["updated_at"],
        status=row["status"],
        approvedAt=row["approved_at"],
        **screenplay.model_dump(),
    )


def row_to_storyboard(row: sqlite3.Row) -> StoryboardOut:
    payload = StoryboardPayload.model_validate(json.loads(row["payload"]))
    return StoryboardOut(
        projectId=row["project_id"],
        model=row["model"],
        targetModel=row["target_model"],
        aspectRatio=row["aspect_ratio"],
        fps=row["fps"],
        totalSeconds=row["total_seconds"],
        screenplayUpdatedAt=row["screenplay_updated_at"],
        updatedAt=row["updated_at"],
        **payload.model_dump(),
    )


def row_to_asset_library(row: sqlite3.Row) -> AssetLibraryOut:
    payload = AssetLibraryPayload.model_validate(json.loads(row["payload"]))
    return AssetLibraryOut(
        projectId=row["project_id"],
        screenplayUpdatedAt=row["screenplay_updated_at"],
        storyboardUpdatedAt=row["storyboard_updated_at"],
        updatedAt=row["updated_at"],
        **payload.model_dump(),
    )


def row_to_asset_batch_plan(
    row: sqlite3.Row, asset_library_updated_at: str
) -> AssetBatchPlanOut:
    payload = AssetBatchPlanPayload.model_validate(json.loads(row["payload"]))
    return AssetBatchPlanOut(
        projectId=row["project_id"],
        current=payload.assetLibraryUpdatedAt == asset_library_updated_at,
        updatedAt=row["updated_at"],
        **payload.model_dump(),
    )


def asset_library_tasks(row: sqlite3.Row) -> list[ProjectTaskOut]:
    library = AssetLibraryPayload.model_validate(json.loads(row["payload"]))
    tasks = [
        ProjectTaskOut(
            id=image.id,
            projectId=row["project_id"],
            type="asset-image",
            status="completed",
            title=f"{item.name}参考图 V{index + 1}",
            assetId=item.id,
            assetKind=item.kind,
            providerTaskId=image.taskId,
            model=image.model,
            resultUrl=image.url,
            cost=image.cost,
            createdAt=image.createdAt,
            updatedAt=image.createdAt,
        )
        for item in library.items
        for index, image in enumerate(item.referenceImages)
    ]
    return sorted(tasks, key=lambda task: task.createdAt, reverse=True)


def row_to_generation_task(row: sqlite3.Row) -> ProjectTaskOut:
    return ProjectTaskOut(
        id=row["id"],
        projectId=row["project_id"],
        type="asset-image",
        status=row["status"],
        title=row["title"],
        assetId=row["asset_id"],
        assetKind=row["asset_kind"],
        providerTaskId=row["provider_task_id"],
        model=row["model"],
        resultUrl=row["result_url"],
        cost=row["cost"],
        batchId=row["batch_id"],
        error=row["error"],
        attemptCount=row["attempt_count"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def validate_asset_library(payload: AssetLibraryPayload) -> None:
    if not payload.items:
        raise ValueError("资产库不能为空")
    ids = [item.id for item in payload.items]
    if len(ids) != len(set(ids)):
        raise ValueError("资产编号存在重复")
    for item in payload.items:
        if not item.id.strip() or not item.name.strip():
            raise ValueError("资产名称和编号不能为空")
        try:
            UUID(item.id)
        except ValueError as error:
            raise ValueError("资产编号格式无效") from error
        if item.status == "confirmed" and any(
            not value.strip()
            for value in (
                item.description,
                item.visualAnchor,
                item.continuityNotes,
                item.referencePrompt,
            )
        ):
            raise ValueError(f"{item.name} 尚未补全说明、视觉锚点、连续性或生图提示词")


def build_asset_library(
    project_id: str,
    screenplay: ScreenplayPayload,
    plan: ScriptPlanPayload | None,
    storyboard_rows: list[sqlite3.Row],
    previous: AssetLibraryPayload | None,
) -> AssetLibraryPayload:
    previous_by_key = {
        (item.kind, item.name): item for item in previous.items
    } if previous else {}
    plan_characters = {item.name: item for item in plan.characters} if plan else {}
    character_data: dict[str, dict[str, list[str]]] = {}
    scene_data: dict[str, dict[str, list[str]]] = {}
    prop_data: dict[str, dict[str, list[str]]] = {}
    scene_descriptions: dict[str, list[str]] = {}

    for episode in screenplay.episodes:
        for scene in episode.scenes:
            appearance = f"第 {episode.episodeNumber} 集 · 第 {scene.index} 场"
            for name in scene.characters:
                data = character_data.setdefault(name, {"appearances": [], "sourceRefs": []})
                data["appearances"].append(appearance)
                data["sourceRefs"].extend(scene.sourceRefs)
            scene_entry = scene_data.setdefault(
                scene.heading, {"appearances": [], "sourceRefs": []}
            )
            scene_entry["appearances"].append(appearance)
            scene_entry["sourceRefs"].extend(scene.sourceRefs)
            scene_descriptions.setdefault(scene.heading, []).append(
                f"{scene.objective}；阻力：{scene.obstacle}"
            )
            for name in scene.props:
                data = prop_data.setdefault(name, {"appearances": [], "sourceRefs": []})
                data["appearances"].append(appearance)
                data["sourceRefs"].extend(scene.sourceRefs)

    character_anchors = {name: [] for name in character_data}
    scene_anchors = {name: [] for name in scene_data}
    prop_anchors = {name: [] for name in prop_data}
    for row in storyboard_rows:
        storyboard = StoryboardPayload.model_validate(json.loads(row["payload"]))
        episode = screenplay.episodes[storyboard.episodeNumber - 1]
        heading_by_index = {scene.index: scene.heading for scene in episode.scenes}
        for group in storyboard.groups:
            for subject in group.subjects:
                for name in character_anchors:
                    if name in subject:
                        character_anchors[name].append(subject)
                for name in prop_anchors:
                    if name in subject:
                        prop_anchors[name].append(subject)
            heading = heading_by_index.get(group.sceneIndex)
            if heading in scene_anchors:
                scene_anchors[heading].append(group.sceneDescription)

    items: list[AssetItem] = []

    def append_item(
        kind: Literal["character", "scene", "prop"],
        name: str,
        appearances: list[str],
        source_refs: list[str],
        description: str,
        anchors: list[str],
        continuity: str,
        prompt_prefix: str,
    ) -> None:
        previous_item = previous_by_key.get((kind, name))
        if previous_item:
            items.append(
                previous_item.model_copy(
                    update={
                        "appearances": unique_strings(appearances),
                        "sourceRefs": unique_strings(source_refs),
                    }
                )
            )
            return
        visual_anchor = "；".join(unique_strings(anchors))
        reference_prompt = "，".join(
            part for part in (prompt_prefix, description, visual_anchor, "中性背景，细节清晰，便于跨镜头保持一致")
            if part
        )
        items.append(
            AssetItem(
                id=str(uuid5(NAMESPACE_URL, f"mingyan:{project_id}:{kind}:{name}")),
                kind=kind,
                name=name,
                appearances=unique_strings(appearances),
                sourceRefs=unique_strings(source_refs),
                description=description,
                visualAnchor=visual_anchor,
                continuityNotes=continuity,
                referencePrompt=reference_prompt,
            )
        )

    for name, data in character_data.items():
        plan_character = plan_characters.get(name)
        description = (
            f"身份：{plan_character.identity}；目标：{plan_character.goal}；人物弧光：{plan_character.arc}"
            if plan_character else ""
        )
        append_item(
            "character",
            name,
            data["appearances"],
            data["sourceRefs"],
            description,
            character_anchors[name],
            f"所有镜头保持{name}的面部、发型、服装层级、体态与伤势状态连续。",
            f"{name}角色定妆照",
        )
    for name, data in scene_data.items():
        append_item(
            "scene",
            name,
            data["appearances"],
            data["sourceRefs"],
            "；".join(unique_strings(scene_descriptions[name])),
            scene_anchors[name],
            f"保持{name}的入口、主要陈设、人物动线、光向与空间轴线一致。",
            f"{name}场景设定图",
        )
    for name, data in prop_data.items():
        append_item(
            "prop",
            name,
            data["appearances"],
            data["sourceRefs"],
            f"剧本关键物品：{name}",
            prop_anchors[name],
            f"保持{name}的形制、材质、尺寸比例、磨损与持有关系一致。",
            f"{name}道具设定图",
        )
    return AssetLibraryPayload(
        standard=previous.standard if previous else AssetStandardSettings(),
        items=items,
    )


def storyboard_group_blueprints(episode: ScreenplayEpisode) -> list[dict]:
    blueprints: list[dict] = []
    episode_cursor = 0
    for scene in episode.scenes:
        beat_ranges: list[tuple[int, int, ScreenplayBeat]] = []
        beat_cursor = 0
        for beat in scene.beats:
            beat_ranges.append((beat_cursor, beat_cursor + beat.estimatedSeconds, beat))
            beat_cursor += beat.estimatedSeconds

        scene_cursor = 0
        while scene_cursor < scene.estimatedSeconds:
            duration = min(15, scene.estimatedSeconds - scene_cursor)
            chunk_end = scene_cursor + duration
            source_beats = [
                {
                    "kind": beat.kind,
                    "speaker": beat.speaker,
                    "text": beat.text,
                    "sourceRef": beat.sourceRef,
                }
                for beat_start, beat_end, beat in beat_ranges
                if beat_start < chunk_end and beat_end > scene_cursor
            ]
            start = episode_cursor + scene_cursor
            blueprints.append(
                {
                    "index": len(blueprints) + 1,
                    "sceneIndex": scene.index,
                    "startSeconds": start,
                    "endSeconds": start + duration,
                    "durationSeconds": duration,
                    "sceneHeading": scene.heading,
                    "characters": scene.characters,
                    "props": scene.props,
                    "sourceBeats": source_beats,
                }
            )
            scene_cursor = chunk_end
        episode_cursor += scene.estimatedSeconds
    return blueprints


def validate_storyboard_structure(
    storyboard: StoryboardPayload,
    episode: ScreenplayEpisode,
    blueprints: list[dict],
) -> None:
    if storyboard.episodeNumber != episode.episodeNumber:
        raise ValueError("分镜集数与已确认剧本不一致")
    if len(storyboard.groups) != len(blueprints):
        raise ValueError("分镜组数量与权威时间轴不一致")
    if not storyboard.styleBible.strip() or not storyboard.continuityNotes:
        raise ValueError("分镜缺少统一视觉规范或连续性约束")

    required_group_fields = (
        "purpose",
        "hookType",
        "metadata",
        "sceneDescription",
        "firstFrameLock",
        "qualityBase",
        "visualStyle",
        "spatialRelations",
        "actionTimeline",
        "cameraLanguage",
        "emotionalTurn",
        "negativePrompt",
        "generationParams",
        "videoPrompt",
    )
    required_segment_fields = (
        "camera",
        "action",
        "motionVisual",
        "expression",
        "environment",
        "effects",
        "sound",
    )
    for group, blueprint in zip(storyboard.groups, blueprints, strict=True):
        for key in ("index", "sceneIndex", "startSeconds", "endSeconds", "durationSeconds"):
            if abs(float(getattr(group, key)) - float(blueprint[key])) > 0.01:
                raise ValueError(f"第 {group.index} 组时间轴或场次被模型改动")
        if group.durationSeconds <= 0 or group.durationSeconds > 15:
            raise ValueError(f"第 {group.index} 组时长必须在 0 到 15 秒之间")
        if not group.subjects or any(
            not getattr(group, field).strip() for field in required_group_fields
        ):
            raise ValueError(f"第 {group.index} 组缺少完整的镜头、空间或提示词描述")
        if not group.segments:
            raise ValueError(f"第 {group.index} 组没有时间段")

        segment_cursor = 0.0
        for segment in group.segments:
            if abs(segment.startSeconds - segment_cursor) > 0.01:
                raise ValueError(f"第 {group.index} 组内时间码不连续")
            if segment.endSeconds <= segment.startSeconds:
                raise ValueError(f"第 {group.index} 组内存在无效时间段")
            if any(
                not getattr(segment, field).strip() for field in required_segment_fields
            ):
                raise ValueError(f"第 {group.index} 组缺少七维分镜描述")
            segment_cursor = segment.endSeconds
        if abs(segment_cursor - group.durationSeconds) > 0.01:
            raise ValueError(f"第 {group.index} 组内时间码未覆盖完整组时长")

    if blueprints and blueprints[-1]["endSeconds"] != episode.estimatedSeconds:
        raise ValueError("服务端分镜时间轴与剧本总时长不一致")


def normalize_screenplay_timing(screenplay: ScreenplayPayload) -> ScreenplayPayload:
    for episode in screenplay.episodes:
        for scene in episode.scenes:
            for beat in scene.beats:
                seconds = max(1, beat.estimatedSeconds)
                if beat.kind in {"dialogue", "voiceover"}:
                    spoken_characters = len(re.sub(r"\s+", "", beat.text))
                    seconds = max(seconds, (spoken_characters + 4) // 5)
                beat.estimatedSeconds = seconds
            scene.estimatedSeconds = sum(beat.estimatedSeconds for beat in scene.beats)
        episode.estimatedSeconds = sum(scene.estimatedSeconds for scene in episode.scenes)
    return screenplay


def apply_screenplay_quality_checks(screenplay: ScreenplayPayload) -> ScreenplayPayload:
    for episode in screenplay.episodes:
        episode.qualityNotes = [
            note
            for note in episode.qualityNotes
            if "时长" not in note and "秒" not in note
        ]
        difference = episode.estimatedSeconds - episode.targetSeconds
        if abs(difference) > 10:
            direction = "超出" if difference > 0 else "少于"
            episode.qualityNotes.insert(
                0,
                (
                    f"自动时长校验：估算 {episode.estimatedSeconds} 秒，"
                    f"{direction}目标 {abs(difference)} 秒；定稿前需要删减或补足。"
                ),
            )
        else:
            episode.qualityNotes.insert(
                0,
                f"自动时长校验：估算 {episode.estimatedSeconds} 秒，处于目标容差内。",
            )
    return screenplay


def validate_screenplay_structure(screenplay: ScreenplayPayload) -> None:
    if screenplay.episodeCount != len(screenplay.episodes):
        raise ValueError("分集数量与剧本内容不一致")
    if [episode.episodeNumber for episode in screenplay.episodes] != list(
        range(1, screenplay.episodeCount + 1)
    ):
        raise ValueError("剧集编号必须从 1 连续排列")
    for episode in screenplay.episodes:
        if episode.targetSeconds != screenplay.targetSeconds or not episode.scenes:
            raise ValueError(f"第 {episode.episodeNumber} 集缺少完整场次或时长设置不一致")
        if [scene.index for scene in episode.scenes] != list(
            range(1, len(episode.scenes) + 1)
        ):
            raise ValueError(f"第 {episode.episodeNumber} 集场次编号不连续")
        for scene in episode.scenes:
            if not scene.beats or not scene.sourceRefs:
                raise ValueError(
                    f"第 {episode.episodeNumber} 集第 {scene.index} 场缺少正文或原文依据"
                )
            for beat in scene.beats:
                if not beat.text.strip() or not beat.sourceRef.strip():
                    raise ValueError(
                        f"第 {episode.episodeNumber} 集第 {scene.index} 场存在空白内容"
                    )


def screenplay_within_timing_tolerance(screenplay: ScreenplayPayload) -> bool:
    return all(
        abs(episode.estimatedSeconds - episode.targetSeconds) <= 10
        for episode in screenplay.episodes
    )


def screenplay_fidelity_ready(screenplay: ScreenplayPayload) -> bool:
    return all(
        episode.fidelityStatus == "passed" for episode in screenplay.episodes
    )


def episode_content_for_comparison(episode: ScreenplayEpisode) -> dict:
    return episode.model_dump(
        exclude={"qualityNotes", "fidelityStatus", "fidelityNotes"}
    )


def preserve_unchanged_fidelity(
    saved: ScreenplayPayload, incoming: ScreenplayPayload
) -> None:
    saved_by_number = {
        episode.episodeNumber: episode for episode in saved.episodes
    }
    for episode in incoming.episodes:
        previous = saved_by_number.get(episode.episodeNumber)
        if previous and episode_content_for_comparison(previous) == episode_content_for_comparison(episode):
            episode.fidelityStatus = previous.fidelityStatus
            episode.fidelityNotes = previous.fidelityNotes
        else:
            episode.fidelityStatus = "unchecked"
            episode.fidelityNotes = []


def split_source_into_episode_segments(
    content: str, episode_count: int
) -> list[tuple[str, str, list[str]]]:
    matches = list(CHAPTER_HEADING.finditer(content))
    if not matches:
        if episode_count != 1:
            raise ValueError("未识别到章节时只能生成 1 集")
        return [("全文", content, [])]
    if episode_count > len(matches):
        raise ValueError("分集数量不能超过已识别章节数")

    chapters: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = 0 if index == 0 else match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        chapters.append((match.group(0).strip(), content[start:end].strip()))

    base_size, remainder = divmod(len(chapters), episode_count)
    segments: list[tuple[str, str, list[str]]] = []
    cursor = 0
    for index in range(episode_count):
        size = base_size + (1 if index < remainder else 0)
        group = chapters[cursor : cursor + size]
        cursor += size
        headings = [heading for heading, _ in group]
        source_range = headings[0] if len(headings) == 1 else f"{headings[0]}—{headings[-1]}"
        segments.append((source_range, "\n\n".join(text for _, text in group), headings))
    return segments


def script_plan_excerpt(plan: dict, chapter_headings: list[str]) -> dict:
    chapter_numbers = {
        number
        for heading in chapter_headings
        for number in re.findall(r"\d+", heading)
    }
    relevant_scenes = []
    for scene in plan.get("scenes", []):
        label = str(scene.get("chapter", ""))
        label_numbers = set(re.findall(r"\d+", label))
        if not chapter_numbers or chapter_numbers.intersection(label_numbers):
            relevant_scenes.append(scene)
    return {
        "title": plan.get("title", ""),
        "format": plan.get("format", ""),
        "logline": plan.get("logline", ""),
        "coreConflict": plan.get("coreConflict", ""),
        "characters": plan.get("characters", []),
        "relationships": plan.get("relationships", []),
        "scenes": relevant_scenes or plan.get("scenes", []),
        "adaptationNotes": plan.get("adaptationNotes", []),
    }


def create_app(
    data_dir: Path | None = None,
    static_dir: Path | None = None,
    credential_store: CredentialStore | None = None,
    model_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    resolved_data_dir = data_dir or Path(
        os.environ.get("MINGYAN_DATA_DIR", Path.home() / ".mingyan-ai")
    )
    database_path = resolved_data_dir / "mingyan.sqlite3"
    credentials = credential_store or SystemCredentialStore()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database_path)
        with connect(database_path) as connection:
            connection.execute(
                """
                UPDATE asset_generation_jobs
                SET status = 'interrupted',
                    error = '本地服务曾在队列执行期间停止；已有服务商任务号时将复用原任务。',
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (utc_now(),),
            )
        yield

    application = FastAPI(title="明琰AI平台本地服务", version="0.1.0", lifespan=lifespan)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": application.version}

    def text_model_settings() -> TextModelSettingsOut:
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM model_settings WHERE kind = ?", ("text",)
            ).fetchone()
        try:
            has_credential = bool(credentials.get("text-model-api-key"))
        except KeyringError as error:
            raise HTTPException(
                status_code=503, detail="无法访问系统凭据库，请检查系统钥匙串服务"
            ) from error
        base_url = row["base_url"] if row else ""
        model = row["model"] if row else ""
        return TextModelSettingsOut(
            provider="openai-compatible",
            baseUrl=base_url,
            model=model,
            hasCredential=has_credential,
            configured=bool(base_url and model and has_credential),
            updatedAt=row["updated_at"] if row else None,
        )

    def text_model_credentials() -> tuple[TextModelSettingsOut, str]:
        settings = text_model_settings()
        if not settings.configured:
            raise HTTPException(status_code=409, detail="请先保存完整的文本模型配置")
        try:
            api_key = credentials.get("text-model-api-key")
        except KeyringError as error:
            raise HTTPException(
                status_code=503, detail="无法访问系统凭据库，请检查系统钥匙串服务"
            ) from error
        if not api_key:
            raise HTTPException(status_code=409, detail="系统凭据库中没有找到 API 密钥")
        return settings, api_key

    def image_model_settings() -> ImageModelSettingsOut:
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM model_settings WHERE kind = ?", ("image",)
            ).fetchone()
        try:
            has_credential = bool(credentials.get("image-model-api-key"))
        except KeyringError as error:
            raise HTTPException(
                status_code=503, detail="无法访问系统凭据库，请检查系统钥匙串服务"
            ) from error
        base_url = row["base_url"] if row else ""
        model = row["model"] if row else ""
        return ImageModelSettingsOut(
            provider="buming-openai-compatible",
            baseUrl=base_url,
            model=model,
            hasCredential=has_credential,
            configured=bool(base_url and model and has_credential),
            updatedAt=row["updated_at"] if row else None,
        )

    def image_model_credentials() -> tuple[ImageModelSettingsOut, str]:
        settings = image_model_settings()
        if not settings.configured:
            raise HTTPException(status_code=409, detail="请先保存完整的图像模型配置")
        try:
            api_key = credentials.get("image-model-api-key")
        except KeyringError as error:
            raise HTTPException(
                status_code=503, detail="无法访问系统凭据库，请检查系统钥匙串服务"
            ) from error
        if not api_key:
            raise HTTPException(status_code=409, detail="系统凭据库中没有找到图像 API 密钥")
        return settings, api_key

    def process_generation_job(job_id: str) -> None:
        with connect(database_path) as connection:
            job = connection.execute(
                "SELECT * FROM asset_generation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if job is None or job["status"] != "running":
            return

        provider_task_id = job["provider_task_id"]
        recoverable = bool(provider_task_id)
        image_path: Path | None = None
        try:
            settings, api_key = image_model_credentials()
            api_root = settings.baseUrl if settings.baseUrl.endswith("/v1") else f"{settings.baseUrl}/v1"
            headers = {"Authorization": f"Bearer {api_key}"}
            status_payload: dict = {}
            with httpx.Client(
                transport=model_transport, timeout=30, follow_redirects=True
            ) as client:
                if not provider_task_id:
                    created = client.post(
                        f"{api_root}/media/generate",
                        headers=headers,
                        json={
                            "model": job["model"],
                            "prompt": job["prompt"],
                            "params": {
                                "version": "flare",
                                "aspect_ratio": job["aspect_ratio"],
                                "resolution": "1K",
                                "quality": "auto",
                                "background": "opaque",
                            },
                        },
                    )
                    if not created.is_success:
                        raise HTTPException(
                            status_code=502,
                            detail=f"图像服务创建任务失败（HTTP {created.status_code}）",
                        )
                    try:
                        provider_task_id = str(
                            created.json().get("data", {}).get("task_id", "")
                        )
                    except (TypeError, ValueError) as error:
                        raise HTTPException(
                            status_code=502, detail="图像服务返回了无法识别的任务数据"
                        ) from error
                    if not provider_task_id:
                        raise HTTPException(status_code=502, detail="图像服务没有返回任务编号")
                    recoverable = True
                    with connect(database_path) as connection:
                        connection.execute(
                            """
                            UPDATE asset_generation_jobs
                            SET provider_task_id = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (provider_task_id, utc_now(), job_id),
                        )

                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    status_response = client.get(
                        f"{api_root}/media/status",
                        headers=headers,
                        params={"task_id": provider_task_id},
                    )
                    if not status_response.is_success:
                        raise HTTPException(
                            status_code=502,
                            detail=f"图像任务查询失败（HTTP {status_response.status_code}）",
                        )
                    try:
                        status_payload = status_response.json()
                    except ValueError as error:
                        raise HTTPException(
                            status_code=502, detail="图像任务状态无法识别"
                        ) from error
                    if status_payload.get("is_final") is True:
                        break
                    time.sleep(3)
                else:
                    raise HTTPException(status_code=504, detail="图像任务等待超时")

                if status_payload.get("state") != "success":
                    recoverable = False
                    raise HTTPException(
                        status_code=502,
                        detail=str(status_payload.get("error") or "图像任务生成失败"),
                    )
                result_url = str(status_payload.get("result_url", ""))
                parsed_result_url = urlparse(result_url)
                if parsed_result_url.scheme not in {"http", "https"} or not parsed_result_url.netloc:
                    recoverable = False
                    raise HTTPException(status_code=502, detail="图像任务没有返回有效结果地址")
                image_response = client.get(result_url)
                if not image_response.is_success:
                    raise HTTPException(
                        status_code=502,
                        detail=f"生成成功，但下载参考图失败（HTTP {image_response.status_code}）",
                    )

            mime_type = image_response.headers.get("content-type", "").split(";", 1)[0]
            suffix = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }.get(mime_type)
            if suffix is None:
                recoverable = False
                raise HTTPException(status_code=502, detail="图像服务返回的文件格式不受支持")
            if not image_response.content or len(image_response.content) > 30 * 1024 * 1024:
                recoverable = False
                raise HTTPException(status_code=502, detail="图像服务返回了空文件或文件过大")

            now = utc_now()
            image_dir = resolved_data_dir / "generated" / job["project_id"] / job["asset_id"]
            image_dir.mkdir(parents=True, exist_ok=True)
            image_path = image_dir / f"{job_id}{suffix}"
            temporary_path = image_dir / f".{job_id}.tmp"
            temporary_path.write_bytes(image_response.content)
            temporary_path.replace(image_path)
            raw_cost = status_payload.get("cost")
            cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else None
            image = AssetImageVersion(
                id=job_id,
                url=f"/api/projects/{job['project_id']}/assets/{job['asset_id']}/images/{job_id}",
                prompt=job["prompt"],
                model=job["model"],
                taskId=provider_task_id,
                aspectRatio=job["aspect_ratio"],
                resolution="1K",
                cost=cost,
                createdAt=now,
            )
            with connect(database_path) as connection:
                asset_row = connection.execute(
                    "SELECT * FROM project_assets WHERE project_id = ?",
                    (job["project_id"],),
                ).fetchone()
                if asset_row is None:
                    raise HTTPException(status_code=404, detail="资产库不存在")
                library = AssetLibraryPayload.model_validate(json.loads(asset_row["payload"]))
                if not any(item.id == job["asset_id"] for item in library.items):
                    raise HTTPException(status_code=404, detail="资产不存在")
                updated_library = library.model_copy(
                    update={
                        "items": [
                            item.model_copy(
                                update={"referenceImages": [*item.referenceImages, image]}
                            )
                            if item.id == job["asset_id"]
                            else item
                            for item in library.items
                        ]
                    }
                )
                connection.execute(
                    "UPDATE project_assets SET payload = ?, updated_at = ? WHERE project_id = ?",
                    (updated_library.model_dump_json(), now, job["project_id"]),
                )
                connection.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?",
                    (now, job["project_id"]),
                )
                connection.execute(
                    """
                    UPDATE asset_generation_jobs
                    SET status = 'completed', provider_task_id = ?, result_url = ?,
                        cost = ?, error = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (provider_task_id, image.url, cost, now, job_id),
                )
        except (
            HTTPException,
            httpx.RequestError,
            sqlite3.Error,
            ValidationError,
            OSError,
        ) as error:
            if image_path is not None:
                image_path.unlink(missing_ok=True)
            if isinstance(error, HTTPException):
                message = str(error.detail)
            elif isinstance(error, httpx.RequestError):
                message = f"图像服务连接中断：{type(error).__name__}"
            else:
                message = str(error) or type(error).__name__
            status = "interrupted" if recoverable else "failed"
            with connect(database_path) as connection:
                connection.execute(
                    """
                    UPDATE asset_generation_jobs
                    SET status = ?, provider_task_id = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, provider_task_id, message, utc_now(), job_id),
                )

    def process_generation_batch(batch_id: str) -> None:
        while True:
            with connect(database_path) as connection:
                running = connection.execute(
                    """
                    SELECT id FROM asset_generation_jobs
                    WHERE batch_id = ? AND status = 'running'
                    """,
                    (batch_id,),
                ).fetchone()
                if running is not None:
                    return
                queued = connection.execute(
                    """
                    SELECT id FROM asset_generation_jobs
                    WHERE batch_id = ? AND status = 'queued'
                    ORDER BY created_at, id LIMIT 1
                    """,
                    (batch_id,),
                ).fetchone()
                if queued is None:
                    return
                claimed = connection.execute(
                    """
                    UPDATE asset_generation_jobs
                    SET status = 'running', error = '', updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (utc_now(), queued["id"]),
                )
            if claimed.rowcount:
                process_generation_job(queued["id"])
                with connect(database_path) as connection:
                    saved = connection.execute(
                        "SELECT status FROM asset_generation_jobs WHERE id = ?",
                        (queued["id"],),
                    ).fetchone()
                if saved is not None and saved["status"] == "interrupted":
                    return

    @application.get("/api/settings/text-model", response_model=TextModelSettingsOut)
    def get_text_model_settings() -> TextModelSettingsOut:
        return text_model_settings()

    @application.put("/api/settings/text-model", response_model=TextModelSettingsOut)
    def update_text_model_settings(
        payload: TextModelSettingsUpdate,
    ) -> TextModelSettingsOut:
        if payload.apiKey:
            try:
                credentials.set("text-model-api-key", payload.apiKey)
            except KeyringError as error:
                raise HTTPException(
                    status_code=503, detail="密钥无法写入系统凭据库，请检查系统钥匙串服务"
                ) from error
        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO model_settings (kind, base_url, model, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(kind) DO UPDATE SET
                    base_url = excluded.base_url,
                    model = excluded.model,
                    updated_at = excluded.updated_at
                """,
                ("text", payload.baseUrl, payload.model, now),
            )
        return text_model_settings()

    @application.post(
        "/api/settings/text-model/test", response_model=TextModelConnectionOut
    )
    def test_text_model_connection() -> TextModelConnectionOut:
        settings, api_key = text_model_credentials()

        models_url = (
            f"{settings.baseUrl}/models"
            if settings.baseUrl.endswith("/v1")
            else f"{settings.baseUrl}/v1/models"
        )
        started_at = time.perf_counter()
        try:
            with httpx.Client(transport=model_transport, timeout=15, follow_redirects=True) as client:
                response = client.get(
                    models_url, headers={"Authorization": f"Bearer {api_key}"}
                )
        except httpx.RequestError as error:
            raise HTTPException(
                status_code=502, detail=f"无法连接模型服务：{type(error).__name__}"
            ) from error

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=502, detail="模型服务拒绝鉴权，请检查 API 密钥")
        if not response.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"模型服务返回 HTTP {response.status_code}，请检查接口地址",
            )
        try:
            model_ids = {
                item.get("id")
                for item in response.json().get("data", [])
                if isinstance(item, dict)
            }
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=502, detail="模型服务返回了无法识别的数据") from error
        if settings.model not in model_ids:
            raise HTTPException(
                status_code=502,
                detail=f"连接成功，但模型列表中没有 {settings.model}",
            )
        return TextModelConnectionOut(
            connected=True,
            model=settings.model,
            latencyMs=latency_ms,
            message="鉴权成功，模型可用",
        )

    @application.get("/api/settings/image-model", response_model=ImageModelSettingsOut)
    def get_image_model_settings() -> ImageModelSettingsOut:
        return image_model_settings()

    @application.put("/api/settings/image-model", response_model=ImageModelSettingsOut)
    def update_image_model_settings(
        payload: ImageModelSettingsUpdate,
    ) -> ImageModelSettingsOut:
        if payload.apiKey:
            try:
                credentials.set("image-model-api-key", payload.apiKey)
            except KeyringError as error:
                raise HTTPException(
                    status_code=503, detail="密钥无法写入系统凭据库，请检查系统钥匙串服务"
                ) from error
        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO model_settings (kind, base_url, model, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(kind) DO UPDATE SET
                    base_url = excluded.base_url,
                    model = excluded.model,
                    updated_at = excluded.updated_at
                """,
                ("image", payload.baseUrl, payload.model, now),
            )
        return image_model_settings()

    @application.post(
        "/api/settings/image-model/test", response_model=TextModelConnectionOut
    )
    def test_image_model_connection() -> TextModelConnectionOut:
        settings, api_key = image_model_credentials()
        models_url = (
            f"{settings.baseUrl}/models"
            if settings.baseUrl.endswith("/v1")
            else f"{settings.baseUrl}/v1/models"
        )
        started_at = time.perf_counter()
        try:
            with httpx.Client(
                transport=model_transport, timeout=15, follow_redirects=True
            ) as client:
                response = client.get(
                    models_url, headers={"Authorization": f"Bearer {api_key}"}
                )
        except httpx.RequestError as error:
            raise HTTPException(
                status_code=502, detail=f"无法连接图像模型服务：{type(error).__name__}"
            ) from error

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=502, detail="图像模型服务拒绝鉴权，请检查 API 密钥")
        if not response.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"图像模型服务返回 HTTP {response.status_code}，请检查接口地址",
            )
        try:
            model_ids = {
                item.get("id")
                for item in response.json().get("data", [])
                if isinstance(item, dict)
            }
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=502, detail="图像模型服务返回了无法识别的数据") from error
        if settings.model not in model_ids:
            raise HTTPException(
                status_code=502,
                detail=f"鉴权成功，但模型列表中没有 {settings.model}",
            )
        return TextModelConnectionOut(
            connected=True,
            model=settings.model,
            latencyMs=latency_ms,
            message="鉴权成功，图像模型可用（未生成图片）",
        )

    @application.get("/api/projects", response_model=list[ProjectOut])
    def list_projects() -> list[ProjectOut]:
        with connect(database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [row_to_project(row) for row in rows]

    @application.post("/api/projects", response_model=ProjectOut, status_code=201)
    def create_project(payload: ProjectCreate) -> ProjectOut:
        project_id = str(uuid4())
        now = utc_now()
        description = payload.description.strip() or "AI 视频项目"
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO projects (id, name, description, stage, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, payload.name, description, "text", now, now),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return row_to_project(row)

    @application.patch("/api/projects/{project_id}/stage", response_model=ProjectOut)
    def update_project_stage(project_id: str, payload: ProjectStageUpdate) -> ProjectOut:
        now = utc_now()
        with connect(database_path) as connection:
            if payload.stage in {"storyboard", "assets", "video"}:
                screenplay = connection.execute(
                    "SELECT * FROM project_screenplays WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                source = connection.execute(
                    "SELECT updated_at FROM project_sources WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                plan = connection.execute(
                    "SELECT updated_at FROM project_script_plans WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                if (
                    screenplay is None
                    or screenplay["status"] != "approved"
                    or source is None
                    or plan is None
                    or screenplay["source_updated_at"] != source["updated_at"]
                    or screenplay["plan_updated_at"] != plan["updated_at"]
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="请先完成逐场剧本编辑并人工确认，再进入分镜阶段",
                    )
            result = connection.execute(
                "UPDATE projects SET stage = ?, updated_at = ? WHERE id = ?",
                (payload.stage, now, project_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="项目不存在")
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return row_to_project(row)

    @application.get("/api/projects/{project_id}/source", response_model=SourceOut | None)
    def get_project_source(project_id: str) -> SourceOut | None:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            row = connection.execute(
                "SELECT * FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_source(row) if row else None

    @application.put("/api/projects/{project_id}/source", response_model=SourceOut)
    def save_project_source(project_id: str, payload: SourceUpsert) -> SourceOut:
        now = utc_now()
        char_count = len(payload.content)
        chapter_count = len(CHAPTER_HEADING.findall(payload.content))
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            connection.execute(
                """
                INSERT INTO project_sources (
                    project_id, title, content, char_count, chapter_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    char_count = excluded.char_count,
                    chapter_count = excluded.chapter_count,
                    updated_at = excluded.updated_at
                """,
                (project_id, payload.title, payload.content, char_count, chapter_count, now),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id)
            )
            row = connection.execute(
                "SELECT * FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_source(row)

    @application.get(
        "/api/projects/{project_id}/analysis", response_model=StoryAnalysisOut | None
    )
    def get_project_analysis(project_id: str) -> StoryAnalysisOut | None:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            row = connection.execute(
                "SELECT * FROM project_analyses WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_analysis(row) if row else None

    @application.post(
        "/api/projects/{project_id}/analysis", response_model=StoryAnalysisOut
    )
    def analyze_project(project_id: str) -> StoryAnalysisOut:
        now = utc_now()
        with connect(database_path) as connection:
            source = connection.execute(
                "SELECT * FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
            if source is None:
                raise HTTPException(status_code=409, detail="请先保存小说原文")
            payload = analyze_story(source["content"])
            connection.execute(
                """
                INSERT INTO project_analyses (
                    project_id, engine, payload, source_updated_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    engine = excluded.engine,
                    payload = excluded.payload,
                    source_updated_at = excluded.source_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    "local-v1",
                    json.dumps(payload, ensure_ascii=False),
                    source["updated_at"],
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM project_analyses WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_analysis(row)

    @application.get(
        "/api/projects/{project_id}/script-plan", response_model=ScriptPlanOut | None
    )
    def get_script_plan(project_id: str) -> ScriptPlanOut | None:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            row = connection.execute(
                "SELECT * FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_script_plan(row) if row else None

    @application.post(
        "/api/projects/{project_id}/script-plan", response_model=ScriptPlanOut
    )
    def generate_script_plan(project_id: str) -> ScriptPlanOut:
        with connect(database_path) as connection:
            source = connection.execute(
                "SELECT * FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
        if source is None:
            raise HTTPException(status_code=409, detail="请先保存小说原文")

        settings, api_key = text_model_credentials()
        chat_url = (
            f"{settings.baseUrl}/chat/completions"
            if settings.baseUrl.endswith("/v1")
            else f"{settings.baseUrl}/v1/chat/completions"
        )
        try:
            with httpx.Client(transport=model_transport, timeout=180, follow_redirects=True) as client:
                response = client.post(
                    chat_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.model,
                        "messages": build_script_messages(source["title"], source["content"]),
                        "temperature": 0.2,
                        "max_tokens": 10000,
                    },
                )
        except httpx.RequestError as error:
            raise HTTPException(
                status_code=502, detail=f"模型请求失败：{type(error).__name__}"
            ) from error
        if not response.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"模型服务返回 HTTP {response.status_code}，剧本策划生成失败",
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            plan = ScriptPlanPayload.model_validate(extract_json_object(content))
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
            raise HTTPException(status_code=502, detail="模型返回的剧本策划结构不完整") from error

        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO project_script_plans (
                    project_id, model, payload, source_updated_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    model = excluded.model,
                    payload = excluded.payload,
                    source_updated_at = excluded.source_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    settings.model,
                    plan.model_dump_json(),
                    source["updated_at"],
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_script_plan(row)

    @application.get(
        "/api/projects/{project_id}/screenplay", response_model=ScreenplayOut | None
    )
    def get_screenplay(project_id: str) -> ScreenplayOut | None:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_screenplay(row) if row else None

    @application.put(
        "/api/projects/{project_id}/screenplay", response_model=ScreenplayOut
    )
    def save_screenplay(
        project_id: str, payload: ScreenplayPayload
    ) -> ScreenplayOut:
        try:
            validate_screenplay_structure(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        now = utc_now()
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            source = connection.execute(
                "SELECT updated_at FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan = connection.execute(
                "SELECT updated_at FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=409, detail="请先生成逐场剧本")
            if source is None or plan is None:
                raise HTTPException(status_code=409, detail="原文或剧本策划不存在")
            if (
                row["source_updated_at"] != source["updated_at"]
                or row["plan_updated_at"] != plan["updated_at"]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="原文或剧本策划已经更新，请重新生成逐场剧本",
                )
            saved_screenplay = ScreenplayPayload.model_validate(json.loads(row["payload"]))
            preserve_unchanged_fidelity(saved_screenplay, payload)
            screenplay = apply_screenplay_quality_checks(
                normalize_screenplay_timing(payload)
            )
            connection.execute(
                """
                UPDATE project_screenplays
                SET payload = ?, status = 'draft', approved_at = NULL, updated_at = ?
                WHERE project_id = ?
                """,
                (screenplay.model_dump_json(), now, project_id),
            )
            connection.execute(
                "UPDATE projects SET stage = 'script', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            saved = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_screenplay(saved)

    @application.post(
        "/api/projects/{project_id}/screenplay/episodes/{episode_number}/refine",
        response_model=ScreenplayOut,
    )
    def refine_screenplay_episode(
        project_id: str, episode_number: int
    ) -> ScreenplayOut:
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            source = connection.execute(
                "SELECT * FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan = connection.execute(
                "SELECT updated_at FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="请先生成逐场剧本")
        if source is None or plan is None or (
            row["source_updated_at"] != source["updated_at"]
            or row["plan_updated_at"] != plan["updated_at"]
        ):
            raise HTTPException(
                status_code=409,
                detail="原文或剧本策划已经更新，请重新生成逐场剧本",
            )

        screenplay = ScreenplayPayload.model_validate(json.loads(row["payload"]))
        if episode_number < 1 or episode_number > screenplay.episodeCount:
            raise HTTPException(status_code=404, detail="剧集不存在")
        current_episode = screenplay.episodes[episode_number - 1]
        segments = split_source_into_episode_segments(
            source["content"], screenplay.episodeCount
        )
        source_range, source_segment, chapter_headings = segments[episode_number - 1]

        settings, api_key = text_model_credentials()
        chat_url = (
            f"{settings.baseUrl}/chat/completions"
            if settings.baseUrl.endswith("/v1")
            else f"{settings.baseUrl}/v1/chat/completions"
        )
        try:
            with httpx.Client(
                transport=model_transport, timeout=180, follow_redirects=True
            ) as client:
                response = client.post(
                    chat_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.model,
                        "messages": build_screenplay_refinement_messages(
                            source["title"],
                            source_segment,
                            source_range,
                            current_episode.model_dump(
                                exclude={"fidelityStatus", "fidelityNotes"}
                            ),
                            screenplay.targetSeconds,
                        ),
                        "temperature": 0.1,
                        "max_tokens": 6000,
                    },
                )
        except httpx.RequestError as error:
            raise HTTPException(
                status_code=502,
                detail=f"第 {episode_number} 集定稿请求失败：{type(error).__name__}",
            ) from error
        if not response.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"模型服务返回 HTTP {response.status_code}，本集定稿失败",
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            refinement_payload = extract_json_object(content)
            if "episode" in refinement_payload:
                result = ScreenplayRefinementResult.model_validate(refinement_payload)
            else:
                result = ScreenplayRefinementResult(
                    episode=ScreenplayEpisode.model_validate(refinement_payload),
                    fidelityStatus="review",
                    fidelityNotes=["模型未返回独立忠实度结论，请人工复核。"],
                    revisionNotes=[],
                )
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
            raise HTTPException(status_code=502, detail="模型返回的单集定稿结构不完整") from error

        refined = result.episode
        if (
            refined.episodeNumber != episode_number
            or refined.targetSeconds != screenplay.targetSeconds
            or len(refined.scenes) != len(current_episode.scenes)
            or [scene.index for scene in refined.scenes]
            != [scene.index for scene in current_episode.scenes]
        ):
            raise HTTPException(
                status_code=502,
                detail="模型改变了集号、目标时长或场次结构，旧稿已保留",
            )
        allowed_references = set(chapter_headings)
        for scene in refined.scenes:
            references = set(scene.sourceRefs)
            references.update(beat.sourceRef for beat in scene.beats)
            if not scene.beats or not scene.sourceRefs or (
                allowed_references and not references.issubset(allowed_references)
            ):
                raise HTTPException(
                    status_code=502,
                    detail="模型返回的原文依据不完整或包含不存在的章节，旧稿已保留",
                )

        refined.sourceRange = source_range
        refined.fidelityStatus = result.fidelityStatus
        refined.fidelityNotes = result.fidelityNotes or [
            "AI辅助复核未返回说明，请人工检查。"
        ]
        if any(
            beat.origin == "suggestion"
            for scene in refined.scenes
            for beat in scene.beats
        ):
            refined.fidelityStatus = "review"
            refined.fidelityNotes.append("本集仍含建议补全内容，需要创作者确认。")
        refined.qualityNotes = [
            note for note in refined.qualityNotes if not note.startswith("AI定稿：")
        ]
        refined.qualityNotes.extend(
            f"AI定稿：{note}" for note in result.revisionNotes
        )

        screenplay.episodes[episode_number - 1] = refined
        screenplay.continuityNotes = [
            f"第 {episode.episodeNumber} 集结束：{episode.endingState}"
            + (f"；待兑现：{episode.hook}" if episode.hook else "")
            for episode in screenplay.episodes
        ]
        try:
            validate_screenplay_structure(screenplay)
        except ValueError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        screenplay = apply_screenplay_quality_checks(
            normalize_screenplay_timing(screenplay)
        )
        refined = screenplay.episodes[episode_number - 1]
        if abs(refined.estimatedSeconds - refined.targetSeconds) > 10:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"模型压缩后估算为 {refined.estimatedSeconds} 秒，仍未进入"
                    f" {refined.targetSeconds}±10 秒范围，旧稿已保留"
                ),
            )

        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                UPDATE project_screenplays
                SET model = ?, payload = ?, status = 'draft', approved_at = NULL, updated_at = ?
                WHERE project_id = ?
                """,
                (settings.model, screenplay.model_dump_json(), now, project_id),
            )
            connection.execute(
                "UPDATE projects SET stage = 'script', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            saved = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_screenplay(saved)

    @application.post(
        "/api/projects/{project_id}/screenplay/approve", response_model=ScreenplayOut
    )
    def approve_screenplay(project_id: str) -> ScreenplayOut:
        now = utc_now()
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            source = connection.execute(
                "SELECT updated_at FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan = connection.execute(
                "SELECT updated_at FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=409, detail="请先生成逐场剧本")
            if source is None or plan is None or (
                row["source_updated_at"] != source["updated_at"]
                or row["plan_updated_at"] != plan["updated_at"]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="原文或剧本策划已经更新，请重新生成逐场剧本",
                )
            screenplay = apply_screenplay_quality_checks(
                normalize_screenplay_timing(
                    ScreenplayPayload.model_validate(json.loads(row["payload"]))
                )
            )
            if not screenplay_within_timing_tolerance(screenplay):
                raise HTTPException(
                    status_code=409,
                    detail="仍有剧集超出目标时长 ±10 秒，请编辑并保存后再确认",
                )
            if not screenplay_fidelity_ready(screenplay):
                raise HTTPException(
                    status_code=409,
                    detail="仍有剧集尚未通过原著忠实度复核，请逐集复核后再确认",
                )
            connection.execute(
                """
                UPDATE project_screenplays
                SET payload = ?, status = 'approved', approved_at = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (screenplay.model_dump_json(), now, now, project_id),
            )
            approved = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_screenplay(approved)

    @application.post(
        "/api/projects/{project_id}/screenplay", response_model=ScreenplayOut
    )
    def generate_screenplay(
        project_id: str, payload: ScreenplayGenerateRequest
    ) -> ScreenplayOut:
        with connect(database_path) as connection:
            source = connection.execute(
                "SELECT * FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan_row = connection.execute(
                "SELECT * FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
        if source is None:
            raise HTTPException(status_code=409, detail="请先保存小说原文")
        if plan_row is None:
            raise HTTPException(status_code=409, detail="请先生成 AI 剧本策划")
        if len(source["content"]) > 60_000:
            raise HTTPException(
                status_code=413,
                detail="第一版单次最多处理 60,000 字符，请先按章节拆分原文",
            )

        plan_payload = json.loads(plan_row["payload"])
        try:
            segments = split_source_into_episode_segments(
                source["content"], payload.episodeCount
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        settings, api_key = text_model_credentials()
        chat_url = (
            f"{settings.baseUrl}/chat/completions"
            if settings.baseUrl.endswith("/v1")
            else f"{settings.baseUrl}/v1/chat/completions"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        episodes: list[ScreenplayEpisode] = []
        with httpx.Client(transport=model_transport, timeout=180, follow_redirects=True) as client:
            for episode_index, (source_range, source_segment, chapter_headings) in enumerate(
                segments, start=1
            ):
                try:
                    response = client.post(
                        chat_url,
                        headers=headers,
                        json={
                            "model": settings.model,
                            "messages": build_screenplay_episode_messages(
                                source["title"],
                                source_segment,
                                script_plan_excerpt(plan_payload, chapter_headings),
                                payload.adaptationMode,
                                payload.targetSeconds,
                                episode_index,
                                payload.episodeCount,
                                source_range,
                            ),
                            "temperature": 0.2,
                            "max_tokens": 6000,
                        },
                    )
                except httpx.RequestError as error:
                    raise HTTPException(
                        status_code=502,
                        detail=f"第 {episode_index} 集模型请求失败：{type(error).__name__}",
                    ) from error
                if not response.is_success:
                    raise HTTPException(
                        status_code=502,
                        detail=f"模型服务返回 HTTP {response.status_code}，第 {episode_index} 集生成失败",
                    )
                try:
                    content = response.json()["choices"][0]["message"]["content"]
                    episode = ScreenplayEpisode.model_validate(extract_json_object(content))
                except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
                    raise HTTPException(
                        status_code=502,
                        detail=f"模型返回的第 {episode_index} 集结构不完整",
                    ) from error
                if (
                    episode.episodeNumber != episode_index
                    or episode.targetSeconds != payload.targetSeconds
                    or not episode.scenes
                ):
                    raise HTTPException(
                        status_code=502,
                        detail=f"模型没有按参数返回第 {episode_index} 集完整剧本",
                    )
                if [scene.index for scene in episode.scenes] != list(
                    range(1, len(episode.scenes) + 1)
                ):
                    raise HTTPException(
                        status_code=502,
                        detail=f"模型返回的第 {episode_index} 集场次编号不连续",
                    )
                allowed_references = set(chapter_headings)
                for scene in episode.scenes:
                    if not scene.beats or not scene.sourceRefs:
                        raise HTTPException(
                            status_code=502,
                            detail=f"模型返回的第 {episode_index} 集场次缺少正文或原文依据",
                        )
                    invalid_references = {
                        reference
                        for reference in scene.sourceRefs
                        if allowed_references and reference not in allowed_references
                    }
                    invalid_references.update(
                        beat.sourceRef
                        for beat in scene.beats
                        if allowed_references and beat.sourceRef not in allowed_references
                    )
                    if invalid_references:
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                f"第 {episode_index} 集包含不存在的章节依据："
                                f"{'、'.join(sorted(invalid_references))}"
                            ),
                        )
                episode.sourceRange = source_range
                episodes.append(episode)

        screenplay = ScreenplayPayload(
            adaptationMode=payload.adaptationMode,
            targetSeconds=payload.targetSeconds,
            episodeCount=payload.episodeCount,
            episodes=episodes,
            continuityNotes=[
                f"第 {episode.episodeNumber} 集结束：{episode.endingState}"
                + (f"；待兑现：{episode.hook}" if episode.hook else "")
                for episode in episodes
            ],
        )

        screenplay = apply_screenplay_quality_checks(
            normalize_screenplay_timing(screenplay)
        )
        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO project_screenplays (
                    project_id, model, payload, source_updated_at, plan_updated_at,
                    status, approved_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', NULL, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    model = excluded.model,
                    payload = excluded.payload,
                    source_updated_at = excluded.source_updated_at,
                    plan_updated_at = excluded.plan_updated_at,
                    status = 'draft',
                    approved_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    settings.model,
                    screenplay.model_dump_json(),
                    source["updated_at"],
                    plan_row["updated_at"],
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            connection.execute(
                "UPDATE projects SET stage = 'script', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return row_to_screenplay(row)

    @application.get(
        "/api/projects/{project_id}/storyboards", response_model=list[StoryboardOut]
    )
    def get_storyboards(project_id: str) -> list[StoryboardOut]:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            rows = connection.execute(
                """
                SELECT * FROM project_storyboards
                WHERE project_id = ?
                ORDER BY episode_number
                """,
                (project_id,),
            ).fetchall()
        return [row_to_storyboard(row) for row in rows]

    @application.post(
        "/api/projects/{project_id}/storyboards/{episode_number}",
        response_model=StoryboardOut,
    )
    def generate_storyboard(
        project_id: str,
        episode_number: int,
        payload: StoryboardGenerateRequest,
    ) -> StoryboardOut:
        with connect(database_path) as connection:
            screenplay_row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            source = connection.execute(
                "SELECT updated_at FROM project_sources WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan = connection.execute(
                "SELECT updated_at FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
        if screenplay_row is None:
            raise HTTPException(status_code=409, detail="请先生成并确认逐场剧本")
        if (
            screenplay_row["status"] != "approved"
            or source is None
            or plan is None
            or screenplay_row["source_updated_at"] != source["updated_at"]
            or screenplay_row["plan_updated_at"] != plan["updated_at"]
        ):
            raise HTTPException(
                status_code=409,
                detail="剧本尚未确认或已过期，请先完成剧本人工确认",
            )

        screenplay = ScreenplayPayload.model_validate(json.loads(screenplay_row["payload"]))
        if episode_number < 1 or episode_number > screenplay.episodeCount:
            raise HTTPException(status_code=404, detail="剧集不存在")
        episode = screenplay.episodes[episode_number - 1]
        blueprints = storyboard_group_blueprints(episode)

        settings, api_key = text_model_credentials()
        chat_url = (
            f"{settings.baseUrl}/chat/completions"
            if settings.baseUrl.endswith("/v1")
            else f"{settings.baseUrl}/v1/chat/completions"
        )
        generated_groups: list[StoryboardGroup] = []
        continuity_notes: list[str] = []
        style_bible = ""
        episode_title = episode.title
        for batch_start in range(0, len(blueprints), 2):
            batch = blueprints[batch_start : batch_start + 2]
            continuity_context = ""
            if generated_groups:
                previous = generated_groups[-1]
                continuity_context = (
                    f"上一组末帧：{previous.firstFrameLock}；"
                    f"空间：{previous.spatialRelations}；"
                    f"末段动作：{previous.segments[-1].action}；"
                    f"末段表情：{previous.segments[-1].expression}"
                )
            try:
                with httpx.Client(
                    transport=model_transport, timeout=240, follow_redirects=True
                ) as client:
                    response = client.post(
                        chat_url,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": settings.model,
                            "messages": build_storyboard_messages(
                                episode.model_dump(),
                                batch,
                                payload.targetModel,
                                payload.aspectRatio,
                                24,
                                continuity_context,
                                style_bible,
                            ),
                            "temperature": 0.25,
                            "max_tokens": 6000,
                        },
                    )
            except httpx.RequestError as error:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"第 {batch_start + 1}—{batch_start + len(batch)} 组分镜请求失败："
                        f"{type(error).__name__}"
                    ),
                ) from error
            if not response.is_success:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"模型服务返回 HTTP {response.status_code}，"
                        f"第 {batch_start + 1}—{batch_start + len(batch)} 组生成失败"
                    ),
                )
            try:
                content = response.json()["choices"][0]["message"]["content"]
                partial = StoryboardPayload.model_validate(extract_json_object(content))
            except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"第 {batch_start + 1}—{batch_start + len(batch)} 组"
                        f"返回结构不完整：{error}"
                    ),
                ) from error
            if len(partial.groups) != len(batch):
                raise HTTPException(
                    status_code=502,
                    detail=f"第 {batch_start + 1} 组起返回数量与时间轴不一致",
                )
            if not style_bible:
                style_bible = partial.styleBible
                episode_title = partial.episodeTitle
            generated_groups.extend(partial.groups)
            for note in partial.continuityNotes:
                if note not in continuity_notes:
                    continuity_notes.append(note)

        storyboard = StoryboardPayload(
            episodeNumber=episode.episodeNumber,
            episodeTitle=episode_title,
            styleBible=style_bible,
            groups=generated_groups,
            continuityNotes=continuity_notes,
        )
        try:
            validate_storyboard_structure(storyboard, episode, blueprints)
        except ValueError as error:
            raise HTTPException(
                status_code=502, detail=f"模型返回的分镜未通过整集校验：{error}"
            ) from error

        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO project_storyboards (
                    project_id, episode_number, model, target_model, aspect_ratio,
                    fps, total_seconds, payload, screenplay_updated_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, episode_number) DO UPDATE SET
                    model = excluded.model,
                    target_model = excluded.target_model,
                    aspect_ratio = excluded.aspect_ratio,
                    fps = excluded.fps,
                    total_seconds = excluded.total_seconds,
                    payload = excluded.payload,
                    screenplay_updated_at = excluded.screenplay_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    episode_number,
                    settings.model,
                    payload.targetModel,
                    payload.aspectRatio,
                    24,
                    episode.estimatedSeconds,
                    storyboard.model_dump_json(),
                    screenplay_row["updated_at"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET stage = 'storyboard', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            row = connection.execute(
                """
                SELECT * FROM project_storyboards
                WHERE project_id = ? AND episode_number = ?
                """,
                (project_id, episode_number),
            ).fetchone()
        return row_to_storyboard(row)

    @application.put(
        "/api/projects/{project_id}/storyboards/{episode_number}",
        response_model=StoryboardOut,
    )
    def save_storyboard(
        project_id: str,
        episode_number: int,
        payload: StoryboardPayload,
    ) -> StoryboardOut:
        with connect(database_path) as connection:
            screenplay_row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            storyboard_row = connection.execute(
                """
                SELECT * FROM project_storyboards
                WHERE project_id = ? AND episode_number = ?
                """,
                (project_id, episode_number),
            ).fetchone()
        if screenplay_row is None or screenplay_row["status"] != "approved":
            raise HTTPException(status_code=409, detail="剧本未确认，不能编辑分镜")
        if storyboard_row is None:
            raise HTTPException(status_code=404, detail="本集分镜不存在")
        if storyboard_row["screenplay_updated_at"] != screenplay_row["updated_at"]:
            raise HTTPException(status_code=409, detail="剧本已更新，请重新生成本集分镜")

        screenplay = ScreenplayPayload.model_validate(json.loads(screenplay_row["payload"]))
        if episode_number < 1 or episode_number > screenplay.episodeCount:
            raise HTTPException(status_code=404, detail="剧集不存在")
        episode = screenplay.episodes[episode_number - 1]
        blueprints = storyboard_group_blueprints(episode)
        try:
            validate_storyboard_structure(payload, episode, blueprints)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                UPDATE project_storyboards
                SET payload = ?, updated_at = ?
                WHERE project_id = ? AND episode_number = ?
                """,
                (payload.model_dump_json(), now, project_id, episode_number),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            saved = connection.execute(
                """
                SELECT * FROM project_storyboards
                WHERE project_id = ? AND episode_number = ?
                """,
                (project_id, episode_number),
            ).fetchone()
        return row_to_storyboard(saved)

    @application.get(
        "/api/projects/{project_id}/assets", response_model=AssetLibraryOut | None
    )
    def get_asset_library(project_id: str) -> AssetLibraryOut | None:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_asset_library(row) if row else None

    @application.get(
        "/api/projects/{project_id}/assets/batch-plan",
        response_model=AssetBatchPlanOut | None,
    )
    def get_asset_batch_plan(project_id: str) -> AssetBatchPlanOut | None:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            asset_row = connection.execute(
                "SELECT updated_at FROM project_assets WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            plan_row = connection.execute(
                "SELECT * FROM asset_batch_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if plan_row is None:
            return None
        if asset_row is None:
            raise HTTPException(status_code=409, detail="资产库不存在，不能读取生产清单")
        return row_to_asset_batch_plan(plan_row, asset_row["updated_at"])

    @application.post(
        "/api/projects/{project_id}/assets/batch-plan",
        response_model=AssetBatchPlanOut,
    )
    def confirm_asset_batch_plan(
        project_id: str, request: AssetBatchPlanCreate
    ) -> AssetBatchPlanOut:
        with connect(database_path) as connection:
            screenplay_row = connection.execute(
                "SELECT status, updated_at FROM project_screenplays WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            asset_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if screenplay_row is None or screenplay_row["status"] != "approved":
            raise HTTPException(status_code=409, detail="剧本未确认，不能确认批量生产清单")
        if asset_row is None:
            raise HTTPException(status_code=404, detail="请先从剧本整理资产")
        if asset_row["screenplay_updated_at"] != screenplay_row["updated_at"]:
            raise HTTPException(status_code=409, detail="剧本已更新，请重新整理资产")

        library = AssetLibraryPayload.model_validate(json.loads(asset_row["payload"]))
        expected_signature = asset_standard_signature(library.standard)
        assets_by_id = {item.id: item for item in library.items}
        selected: list[AssetItem] = []
        for asset_id in request.assetIds:
            try:
                UUID(asset_id)
            except ValueError as error:
                raise HTTPException(status_code=422, detail="生产清单包含无效资产编号") from error
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="生产清单包含不存在的资产")
            if asset.status != "confirmed":
                raise HTTPException(status_code=409, detail=f"{asset.name} 尚未确认，不能加入生产清单")
            if not asset.referencePrompt.strip():
                raise HTTPException(status_code=422, detail=f"{asset.name} 的生图提示词为空")
            if asset.promptStandardSignature != expected_signature:
                raise HTTPException(
                    status_code=409,
                    detail=f"{asset.name} 尚未按当前资产标准重编提示词",
                )
            selected.append(asset)

        cost_samples = [
            image.cost
            for item in library.items
            for image in item.referenceImages
            if image.cost is not None
        ]
        estimated_unit_cost = (
            round(sum(cost_samples) / len(cost_samples), 4) if cost_samples else None
        )
        estimated_total_cost = (
            round(estimated_unit_cost * len(selected), 4)
            if estimated_unit_cost is not None
            else None
        )
        now = utc_now()
        payload = AssetBatchPlanPayload(
            items=[
                AssetBatchPlanItem(
                    assetId=item.id,
                    assetKind=item.kind,
                    name=item.name,
                    prompt=item.referencePrompt,
                    aspectRatio=asset_aspect_ratio(
                        library.standard.visualStandard, item.kind
                    ),
                    existingVersionCount=len(item.referenceImages),
                )
                for item in selected
            ],
            estimatedUnitCost=estimated_unit_cost,
            estimatedTotalCost=estimated_total_cost,
            costSampleCount=len(cost_samples),
            assetLibraryUpdatedAt=asset_row["updated_at"],
            confirmedAt=now,
        )
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO asset_batch_plans (project_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (project_id, payload.model_dump_json(), now),
            )
            saved = connection.execute(
                "SELECT * FROM asset_batch_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return row_to_asset_batch_plan(saved, asset_row["updated_at"])

    @application.post(
        "/api/projects/{project_id}/assets/batch-plan/queue",
        response_model=list[ProjectTaskOut],
    )
    def queue_asset_batch_plan(
        project_id: str, background_tasks: BackgroundTasks
    ) -> list[ProjectTaskOut]:
        settings, _ = image_model_credentials()
        with connect(database_path) as connection:
            asset_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan_row = connection.execute(
                "SELECT * FROM asset_batch_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
            active = connection.execute(
                """
                SELECT id FROM asset_generation_jobs
                WHERE project_id = ? AND status IN ('queued', 'running', 'interrupted')
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if asset_row is None:
            raise HTTPException(status_code=404, detail="资产库不存在")
        if plan_row is None:
            raise HTTPException(status_code=409, detail="请先确认批量生产清单")
        plan = row_to_asset_batch_plan(plan_row, asset_row["updated_at"])
        if not plan.current:
            raise HTTPException(status_code=409, detail="资产已更新，请重新审查并确认生产清单")
        if active is not None:
            raise HTTPException(status_code=409, detail="已有未完成的生成队列，请先处理任务中心中的任务")

        library = AssetLibraryPayload.model_validate(json.loads(asset_row["payload"]))
        expected_signature = asset_standard_signature(library.standard)
        assets_by_id = {item.id: item for item in library.items}
        for plan_item in plan.items:
            asset = assets_by_id.get(plan_item.assetId)
            if (
                asset is None
                or asset.status != "confirmed"
                or asset.referencePrompt != plan_item.prompt
                or asset.promptStandardSignature != expected_signature
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"{plan_item.name} 已发生变化，请重新确认生产清单",
                )

        batch_id = str(uuid4())
        with connect(database_path) as connection:
            for item in plan.items:
                now = utc_now()
                connection.execute(
                    """
                    INSERT INTO asset_generation_jobs (
                        id, project_id, batch_id, asset_id, asset_kind, title,
                        prompt, aspect_ratio, model, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        str(uuid4()),
                        project_id,
                        batch_id,
                        item.assetId,
                        item.assetKind,
                        f"{item.name}参考图 V{item.existingVersionCount + 1}",
                        item.prompt,
                        item.aspectRatio,
                        settings.model,
                        now,
                        now,
                    ),
                )
            rows = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE batch_id = ? ORDER BY created_at, id
                """,
                (batch_id,),
            ).fetchall()
        background_tasks.add_task(process_generation_batch, batch_id)
        return [row_to_generation_task(row) for row in rows]

    @application.get(
        "/api/projects/{project_id}/tasks", response_model=list[ProjectTaskOut]
    )
    def get_project_tasks(project_id: str) -> list[ProjectTaskOut]:
        with connect(database_path) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            asset_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
            job_rows = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE project_id = ? ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        jobs = [row_to_generation_task(row) for row in job_rows]
        job_ids = {task.id for task in jobs}
        legacy = [
            task
            for task in (asset_library_tasks(asset_row) if asset_row else [])
            if task.id not in job_ids
        ]
        return sorted([*jobs, *legacy], key=lambda task: task.createdAt, reverse=True)

    @application.post(
        "/api/projects/{project_id}/tasks/{task_id}/retry",
        response_model=ProjectTaskOut,
    )
    def retry_generation_task(
        project_id: str, task_id: str, background_tasks: BackgroundTasks
    ) -> ProjectTaskOut:
        with connect(database_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE id = ? AND project_id = ?
                """,
                (task_id, project_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="生成任务不存在")
            if row["status"] != "failed":
                raise HTTPException(status_code=409, detail="只有失败任务可以重新生成")
            connection.execute(
                """
                UPDATE asset_generation_jobs
                SET status = 'queued', provider_task_id = '', result_url = '',
                    cost = NULL, error = '', attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), task_id),
            )
            saved = connection.execute(
                "SELECT * FROM asset_generation_jobs WHERE id = ?", (task_id,)
            ).fetchone()
        background_tasks.add_task(process_generation_batch, row["batch_id"])
        return row_to_generation_task(saved)

    @application.post(
        "/api/projects/{project_id}/tasks/resume",
        response_model=list[ProjectTaskOut],
    )
    def resume_generation_tasks(
        project_id: str, background_tasks: BackgroundTasks
    ) -> list[ProjectTaskOut]:
        with connect(database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE project_id = ? AND status IN ('queued', 'interrupted')
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=409, detail="没有可恢复的生成任务")
            connection.execute(
                """
                UPDATE asset_generation_jobs
                SET status = 'queued', error = '', updated_at = ?
                WHERE project_id = ? AND status = 'interrupted'
                """,
                (utc_now(), project_id),
            )
            saved = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE project_id = ? AND status = 'queued'
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
        for batch_id in dict.fromkeys(row["batch_id"] for row in saved):
            background_tasks.add_task(process_generation_batch, batch_id)
        return [row_to_generation_task(row) for row in saved]

    @application.get(
        "/api/projects/{project_id}/assets/{asset_id}/images/{image_id}"
    )
    def get_asset_reference_image(
        project_id: str, asset_id: str, image_id: str
    ) -> FileResponse:
        try:
            UUID(project_id)
            UUID(asset_id)
            UUID(image_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="参考图不存在") from error
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="资产库不存在")
        library = AssetLibraryPayload.model_validate(json.loads(row["payload"]))
        asset = next((item for item in library.items if item.id == asset_id), None)
        if asset is None or not any(image.id == image_id for image in asset.referenceImages):
            raise HTTPException(status_code=404, detail="参考图不存在")
        image_dir = resolved_data_dir / "generated" / project_id / asset_id
        candidates = [
            path
            for suffix in (".png", ".jpg", ".webp")
            if (path := image_dir / f"{image_id}{suffix}").is_file()
        ]
        if not candidates:
            raise HTTPException(status_code=404, detail="本地参考图文件不存在")
        return FileResponse(candidates[0])

    @application.post(
        "/api/projects/{project_id}/assets/extract", response_model=AssetLibraryOut
    )
    def extract_asset_library(project_id: str) -> AssetLibraryOut:
        with connect(database_path) as connection:
            screenplay_row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            plan_row = connection.execute(
                "SELECT * FROM project_script_plans WHERE project_id = ?", (project_id,)
            ).fetchone()
            storyboard_rows = connection.execute(
                """
                SELECT * FROM project_storyboards
                WHERE project_id = ? AND screenplay_updated_at = ?
                ORDER BY episode_number
                """,
                (project_id, screenplay_row["updated_at"] if screenplay_row else ""),
            ).fetchall()
            previous_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if screenplay_row is None or screenplay_row["status"] != "approved":
            raise HTTPException(status_code=409, detail="请先完成人工确认剧本")

        screenplay = ScreenplayPayload.model_validate(json.loads(screenplay_row["payload"]))
        plan = (
            ScriptPlanPayload.model_validate(json.loads(plan_row["payload"]))
            if plan_row else None
        )
        previous = (
            AssetLibraryPayload.model_validate(json.loads(previous_row["payload"]))
            if previous_row else None
        )
        library = build_asset_library(
            project_id, screenplay, plan, storyboard_rows, previous
        )
        try:
            validate_asset_library(library)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        now = utc_now()
        storyboard_updated_at = max(
            (row["updated_at"] for row in storyboard_rows), default=None
        )
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO project_assets (
                    project_id, payload, screenplay_updated_at,
                    storyboard_updated_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    payload = excluded.payload,
                    screenplay_updated_at = excluded.screenplay_updated_at,
                    storyboard_updated_at = excluded.storyboard_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    library.model_dump_json(),
                    screenplay_row["updated_at"],
                    storyboard_updated_at,
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET stage = 'assets', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            saved = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_asset_library(saved)

    @application.put(
        "/api/projects/{project_id}/assets", response_model=AssetLibraryOut
    )
    def save_asset_library(
        project_id: str, payload: AssetLibraryPayload
    ) -> AssetLibraryOut:
        try:
            validate_asset_library(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        with connect(database_path) as connection:
            screenplay_row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            library_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if screenplay_row is None or screenplay_row["status"] != "approved":
            raise HTTPException(status_code=409, detail="剧本未确认，不能保存资产")
        if library_row is None:
            raise HTTPException(status_code=404, detail="请先从剧本整理资产")
        if library_row["screenplay_updated_at"] != screenplay_row["updated_at"]:
            raise HTTPException(status_code=409, detail="剧本已更新，请重新整理资产")

        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                """
                UPDATE project_assets
                SET payload = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (payload.model_dump_json(), now, project_id),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            saved = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_asset_library(saved)

    @application.post(
        "/api/projects/{project_id}/assets/{asset_id}/images",
        response_model=AssetLibraryOut,
    )
    def generate_asset_reference_image(
        project_id: str, asset_id: str
    ) -> AssetLibraryOut:
        try:
            UUID(project_id)
            UUID(asset_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="资产不存在") from error
        with connect(database_path) as connection:
            screenplay_row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?", (project_id,)
            ).fetchone()
            library_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if screenplay_row is None or screenplay_row["status"] != "approved":
            raise HTTPException(status_code=409, detail="剧本未确认，不能生成资产参考图")
        if library_row is None:
            raise HTTPException(status_code=404, detail="请先从剧本整理资产")
        if library_row["screenplay_updated_at"] != screenplay_row["updated_at"]:
            raise HTTPException(status_code=409, detail="剧本已更新，请重新整理资产")

        library = AssetLibraryPayload.model_validate(json.loads(library_row["payload"]))
        asset = next((item for item in library.items if item.id == asset_id), None)
        if asset is None:
            raise HTTPException(status_code=404, detail="资产不存在")
        if asset.status != "confirmed":
            raise HTTPException(status_code=409, detail="请先确认资产文字规范再生成参考图")
        if not asset.referencePrompt.strip():
            raise HTTPException(status_code=422, detail="资产生图提示词不能为空")
        if asset.promptStandardSignature != asset_standard_signature(library.standard):
            raise HTTPException(
                status_code=409,
                detail="该资产尚未按当前资产标准重编提示词",
            )

        settings, api_key = image_model_credentials()
        aspect_ratio = asset_aspect_ratio(library.standard.visualStandard, asset.kind)
        api_root = settings.baseUrl if settings.baseUrl.endswith("/v1") else f"{settings.baseUrl}/v1"
        headers = {"Authorization": f"Bearer {api_key}"}
        task_id = ""
        status_payload: dict = {}
        try:
            with httpx.Client(
                transport=model_transport, timeout=30, follow_redirects=True
            ) as client:
                created = client.post(
                    f"{api_root}/media/generate",
                    headers=headers,
                    json={
                        "model": settings.model,
                        "prompt": asset.referencePrompt,
                        "params": {
                            "version": "flare",
                            "aspect_ratio": aspect_ratio,
                            "resolution": "1K",
                            "quality": "auto",
                            "background": "opaque",
                        },
                    },
                )
                if not created.is_success:
                    raise HTTPException(
                        status_code=502,
                        detail=f"图像服务创建任务失败（HTTP {created.status_code}）",
                    )
                try:
                    task_id = str(created.json().get("data", {}).get("task_id", ""))
                except (TypeError, ValueError) as error:
                    raise HTTPException(status_code=502, detail="图像服务返回了无法识别的任务数据") from error
                if not task_id:
                    raise HTTPException(status_code=502, detail="图像服务没有返回任务编号")

                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    status_response = client.get(
                        f"{api_root}/media/status",
                        headers=headers,
                        params={"task_id": task_id},
                    )
                    if not status_response.is_success:
                        raise HTTPException(
                            status_code=502,
                            detail=f"图像任务查询失败（HTTP {status_response.status_code}）",
                        )
                    try:
                        status_payload = status_response.json()
                    except ValueError as error:
                        raise HTTPException(status_code=502, detail="图像任务状态无法识别") from error
                    if status_payload.get("is_final") is True:
                        break
                    time.sleep(3)
                else:
                    raise HTTPException(
                        status_code=504,
                        detail=f"图像任务等待超时，任务号：{task_id}；请勿重复生成",
                    )

                if status_payload.get("state") != "success":
                    detail = str(status_payload.get("error") or "图像任务生成失败")
                    raise HTTPException(status_code=502, detail=detail)
                result_url = str(status_payload.get("result_url", ""))
                parsed_result_url = urlparse(result_url)
                if parsed_result_url.scheme not in {"http", "https"} or not parsed_result_url.netloc:
                    raise HTTPException(status_code=502, detail="图像任务没有返回有效结果地址")
                image_response = client.get(result_url)
                if not image_response.is_success:
                    raise HTTPException(
                        status_code=502,
                        detail=f"生成成功，但下载参考图失败（HTTP {image_response.status_code}）",
                    )
        except httpx.RequestError as error:
            suffix = f"，任务号：{task_id}；请勿重复生成" if task_id else ""
            raise HTTPException(
                status_code=502,
                detail=f"图像服务连接中断：{type(error).__name__}{suffix}",
            ) from error

        mime_type = image_response.headers.get("content-type", "").split(";", 1)[0]
        suffix_by_mime = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
        suffix = suffix_by_mime.get(mime_type)
        if suffix is None:
            raise HTTPException(status_code=502, detail="图像服务返回的文件格式不受支持")
        if not image_response.content or len(image_response.content) > 30 * 1024 * 1024:
            raise HTTPException(status_code=502, detail="图像服务返回了空文件或文件过大")

        now = utc_now()
        image_id = str(uuid4())
        image_dir = resolved_data_dir / "generated" / project_id / asset_id
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"{image_id}{suffix}"
        temporary_path = image_dir / f".{image_id}.tmp"
        temporary_path.write_bytes(image_response.content)
        temporary_path.replace(image_path)
        raw_cost = status_payload.get("cost")
        cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else None
        image = AssetImageVersion(
            id=image_id,
            url=f"/api/projects/{project_id}/assets/{asset_id}/images/{image_id}",
            prompt=asset.referencePrompt,
            model=settings.model,
            taskId=task_id,
            aspectRatio=aspect_ratio,
            resolution="1K",
            cost=cost,
            createdAt=now,
        )
        updated_library = library.model_copy(
            update={
                "items": [
                    item.model_copy(
                        update={"referenceImages": [*item.referenceImages, image]}
                    )
                    if item.id == asset_id
                    else item
                    for item in library.items
                ]
            }
        )
        try:
            with connect(database_path) as connection:
                connection.execute(
                    "UPDATE project_assets SET payload = ?, updated_at = ? WHERE project_id = ?",
                    (updated_library.model_dump_json(), now, project_id),
                )
                connection.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id)
                )
                saved = connection.execute(
                    "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
                ).fetchone()
        except sqlite3.Error:
            image_path.unlink(missing_ok=True)
            raise
        return row_to_asset_library(saved)

    @application.put(
        "/api/projects/{project_id}/assets/{asset_id}/images/{image_id}/primary",
        response_model=AssetLibraryOut,
    )
    def set_primary_asset_reference_image(
        project_id: str, asset_id: str, image_id: str
    ) -> AssetLibraryOut:
        try:
            UUID(project_id)
            UUID(asset_id)
            UUID(image_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="参考图不存在") from error
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="资产库不存在")
        library = AssetLibraryPayload.model_validate(json.loads(row["payload"]))
        asset = next((item for item in library.items if item.id == asset_id), None)
        if asset is None or not any(image.id == image_id for image in asset.referenceImages):
            raise HTTPException(status_code=404, detail="参考图不存在")
        updated_library = library.model_copy(
            update={
                "items": [
                    item.model_copy(update={"primaryReferenceImageId": image_id})
                    if item.id == asset_id
                    else item
                    for item in library.items
                ]
            }
        )
        now = utc_now()
        with connect(database_path) as connection:
            connection.execute(
                "UPDATE project_assets SET payload = ?, updated_at = ? WHERE project_id = ?",
                (updated_library.model_dump_json(), now, project_id),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id)
            )
            saved = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row_to_asset_library(saved)

    resolved_static_dir = static_dir
    if resolved_static_dir is None:
        candidate = Path(__file__).resolve().parent.parent / "dist"
        resolved_static_dir = candidate if candidate.is_dir() else None

    if resolved_static_dir and resolved_static_dir.is_dir():
        application.mount("/", StaticFiles(directory=resolved_static_dir, html=True), name="web")

    return application


app = create_app()
