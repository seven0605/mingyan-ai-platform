from __future__ import annotations

import base64
import binascii
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

from server.asset_tunnel import TemporaryAssetTunnel
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
VIDEO_REQUEST_SECONDS = 30


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


class VideoModelSettingsUpdate(TextModelSettingsUpdate):
    pass


class VideoModelSettingsOut(BaseModel):
    provider: Literal["shuikule-openai-compatible"]
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
    identityReferenceImageId: str = ""
    role: Literal["asset-card", "state"] = "asset-card"
    stateLabel: str = ""
    createdAt: str


class AssetIdentityMaster(BaseModel):
    id: str
    url: str
    sourceImageId: str
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
    identityMasters: list[AssetIdentityMaster] = Field(default_factory=list)
    identityMasterId: str | None = None

    @model_validator(mode="after")
    def validate_primary_reference_image(self) -> "AssetItem":
        image_ids = {image.id for image in self.referenceImages}
        if self.primaryReferenceImageId and self.primaryReferenceImageId not in image_ids:
            raise ValueError("主参考图必须来自当前资产的历史版本")
        if self.referenceImages and not self.primaryReferenceImageId:
            self.primaryReferenceImageId = self.referenceImages[0].id
        identity_master_ids = {master.id for master in self.identityMasters}
        if self.identityMasterId and self.identityMasterId not in identity_master_ids:
            raise ValueError("身份母版必须来自当前角色的母版历史")
        if self.identityMasters and not self.identityMasterId:
            self.identityMasterId = self.identityMasters[0].id
        return self


class AssetIdentityMasterCreate(BaseModel):
    sourceImageId: str
    imageData: str = Field(min_length=32, max_length=14_000_000)


class AssetImageGenerateRequest(BaseModel):
    mode: Literal["asset-card", "state"] = "asset-card"
    stateLabel: str = Field(default="", max_length=80)
    statePrompt: str = Field(default="", max_length=4000)

    @field_validator("stateLabel", "statePrompt")
    @classmethod
    def strip_state_text(cls, value: str) -> str:
        return value.strip()


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


ASSET_PROMPT_TEMPLATE_VERSION = "2026-11-04.8"


def asset_standard_signature(settings: AssetStandardSettings) -> str:
    return (
        f"{settings.visualStandard}|{settings.costumeEra}|"
        f"{ASSET_PROMPT_TEMPLATE_VERSION}"
    )


def is_collective_character(kind: str, name: str) -> bool:
    return kind == "character" and bool(
        re.search(r"(?:们|众人|卫众|护卫们|婆子侍女)$", name.strip())
    )


def asset_aspect_ratio(
    standard: str, kind: Literal["character", "scene", "prop"], name: str = ""
) -> str:
    if is_collective_character(kind, name):
        return "16:9"
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


class VideoPlanAssetImageOption(BaseModel):
    id: str
    url: str
    label: str
    identityReferenceImageId: str = ""
    identityMasterId: str = ""
    identityMasterUrl: str = ""


class VideoPlanAssetReference(BaseModel):
    assetId: str
    kind: Literal["character", "scene", "prop"]
    name: str
    imageId: str
    imageUrl: str
    direct: bool
    identityMasterId: str = ""
    identityMasterUrl: str = ""
    availableImages: list[VideoPlanAssetImageOption]


class VideoProductionPlanItem(BaseModel):
    id: str
    episodeNumber: int
    episodeTitle: str
    groupIndex: int
    sceneIndex: int
    durationSeconds: int
    aspectRatio: Literal["16:9", "9:16"]
    targetModel: Literal["seedance-2.0", "sora-2", "kling-3.0", "veo-3.1"]
    purpose: str
    prompt: str
    assetReferences: list[VideoPlanAssetReference]
    blockingReasons: list[str]
    ready: bool


class VideoPlanConfirm(BaseModel):
    itemIds: list[str] = Field(min_length=1, max_length=100)
    referenceImageIds: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("itemIds")
    @classmethod
    def validate_item_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("视频生产清单不能包含重复镜头组")
        return values


class VideoPlanSelectionPayload(BaseModel):
    selectedItemIds: list[str]
    referenceImageIds: dict[str, dict[str, str]] = Field(default_factory=dict)


class VideoProductionPlanOut(BaseModel):
    projectId: str
    items: list[VideoProductionPlanItem]
    selectedItemIds: list[str]
    referenceImageIds: dict[str, dict[str, str]]
    storyboardUpdatedAt: str
    assetLibraryUpdatedAt: str
    current: bool
    confirmedAt: str | None = None


class AssetTunnelStatusOut(BaseModel):
    provider: Literal["cloudflare-quick-tunnel"]
    installed: bool
    running: bool
    projectId: str | None
    publicUrl: str | None
    exposedAssetCount: int
    error: str
    warning: str


class ProjectTaskOut(BaseModel):
    id: str
    projectId: str
    type: Literal["asset-image", "video"]
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    title: str
    assetId: str
    assetKind: Literal["character", "scene", "prop", "video"]
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS video_production_plans (
                project_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                storyboard_updated_at TEXT NOT NULL,
                asset_library_updated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS video_generation_jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                plan_item_id TEXT NOT NULL,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                seconds INTEGER NOT NULL,
                aspect_ratio TEXT NOT NULL,
                reference_assets TEXT NOT NULL,
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


def build_video_plan_items(
    storyboard_rows: list[sqlite3.Row], asset_row: sqlite3.Row
) -> tuple[list[VideoProductionPlanItem], str, str]:
    library = AssetLibraryPayload.model_validate(json.loads(asset_row["payload"]))
    storyboard_updated_at = max(row["updated_at"] for row in storyboard_rows)
    asset_library_updated_at = asset_row["updated_at"]
    library_matches_storyboard = (
        asset_row["storyboard_updated_at"] == storyboard_updated_at
    )
    items: list[VideoProductionPlanItem] = []
    for row in storyboard_rows:
        storyboard = row_to_storyboard(row)
        for group in storyboard.groups:
            search_text = "\n".join(
                [
                    *group.subjects,
                    group.sceneDescription,
                    group.videoPrompt,
                    group.metadata,
                    group.keyDialogue,
                ]
            )
            appearance = (
                f"第 {storyboard.episodeNumber} 集 · 第 {group.sceneIndex} 场"
            )
            references: list[VideoPlanAssetReference] = []
            blocking_reasons: list[str] = []
            for asset in library.items:
                direct = bool(asset.name.strip() and asset.name in search_text)
                contextual = (
                    asset.kind == "scene" and appearance in asset.appearances
                )
                if not direct and not contextual:
                    continue
                primary = next(
                    (
                        image
                        for image in asset.referenceImages
                        if image.id == asset.primaryReferenceImageId
                    ),
                    asset.referenceImages[0] if asset.referenceImages else None,
                )
                requires_reference = asset.kind != "prop"
                if direct and requires_reference and asset.status != "confirmed":
                    blocking_reasons.append(f"{asset.name} 尚未确认")
                elif direct and requires_reference and primary is None:
                    blocking_reasons.append(f"{asset.name} 缺少主参考图")
                if primary is not None and asset.status == "confirmed":
                    identity_masters_by_id = {
                        master.id: master for master in asset.identityMasters
                    }
                    active_identity_master = identity_masters_by_id.get(
                        asset.identityMasterId or ""
                    )
                    available_images: list[VideoPlanAssetImageOption] = []
                    for index, image in enumerate(asset.referenceImages):
                        identity_master = identity_masters_by_id.get(
                            image.identityReferenceImageId
                        ) or active_identity_master
                        available_images.append(
                            VideoPlanAssetImageOption(
                                id=image.id,
                                url=image.url,
                                label=(
                                    f"V{index + 1} · {image.stateLabel}"
                                    if image.role == "state" and image.stateLabel
                                    else f"V{index + 1} · 资产卡"
                                ),
                                identityReferenceImageId=(
                                    image.identityReferenceImageId
                                ),
                                identityMasterId=(
                                    identity_master.id if identity_master else ""
                                ),
                                identityMasterUrl=(
                                    identity_master.url if identity_master else ""
                                ),
                            )
                        )
                    primary_option = next(
                        image for image in available_images if image.id == primary.id
                    )
                    references.append(
                        VideoPlanAssetReference(
                            assetId=asset.id,
                            kind=asset.kind,
                            name=asset.name,
                            imageId=primary.id,
                            imageUrl=primary.url,
                            direct=direct,
                            identityMasterId=primary_option.identityMasterId,
                            identityMasterUrl=primary_option.identityMasterUrl,
                            availableImages=available_images,
                        )
                    )
            if not group.videoPrompt.strip():
                blocking_reasons.append("视频提示词为空")
            if not references:
                blocking_reasons.append("没有可用的已确认资产主参考图")
            if not library_matches_storyboard:
                blocking_reasons.append("分镜已更新，请重新整理资产库")
            blocking_reasons = unique_strings(blocking_reasons)
            items.append(
                VideoProductionPlanItem(
                    id=f"e{storyboard.episodeNumber}-g{group.index}",
                    episodeNumber=storyboard.episodeNumber,
                    episodeTitle=storyboard.episodeTitle,
                    groupIndex=group.index,
                    sceneIndex=group.sceneIndex,
                    durationSeconds=group.durationSeconds,
                    aspectRatio=storyboard.aspectRatio,
                    targetModel=storyboard.targetModel,
                    purpose=group.purpose,
                    prompt=compile_storyboard_group_prompt(group),
                    assetReferences=references,
                    blockingReasons=blocking_reasons,
                    ready=not blocking_reasons,
                )
            )
    return items, storyboard_updated_at, asset_library_updated_at


def apply_video_reference_image_ids(
    items: list[VideoProductionPlanItem],
    reference_image_ids: dict[str, dict[str, str]],
) -> None:
    for item in items:
        item_selections = reference_image_ids.get(item.id, {})
        for reference in item.assetReferences:
            image_id = item_selections.get(reference.assetId)
            if not image_id:
                continue
            option = next(
                (image for image in reference.availableImages if image.id == image_id),
                None,
            )
            if option is not None:
                reference.imageId = option.id
                reference.imageUrl = option.url
                reference.identityMasterId = option.identityMasterId
                reference.identityMasterUrl = option.identityMasterUrl


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


def row_to_video_generation_task(row: sqlite3.Row) -> ProjectTaskOut:
    return ProjectTaskOut(
        id=row["id"],
        projectId=row["project_id"],
        type="video",
        status=row["status"],
        title=row["title"],
        assetId=row["plan_item_id"],
        assetKind="video",
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


def compile_storyboard_group_prompt(group: StoryboardGroup) -> str:
    beats = []
    for index, segment in enumerate(group.segments, start=1):
        beats.append(
            "\n".join(
                [
                    f"镜头节拍 {index}",
                    f"镜头：{segment.camera}",
                    f"动作：{segment.action}",
                    f"运动视觉：{segment.motionVisual}",
                    f"表演：{segment.expression}",
                    f"环境：{segment.environment}",
                    f"特效：{segment.effects}",
                    f"声音：{segment.sound}",
                ]
            )
        )
    subjects = "、".join(group.subjects)
    beat_text = "\n\n".join(beats)
    return "\n\n".join(
        [
            f"【首帧锁定】{group.firstFrameLock}",
            f"【场景与空间】{group.sceneDescription}；{group.spatialRelations}",
            f"【人物与物品视觉锚点】{subjects}",
            f"【动作与表演节拍】\n{beat_text}",
            f"【情绪转折】{group.emotionalTurn}",
            f"【动作时间逻辑】{group.actionTimeline}",
            f"【摄影语言】{group.cameraLanguage}",
            f"【关键对白】{group.keyDialogue or '无'}",
            f"【画面标准】{group.qualityBase}；{group.visualStyle}；{group.generationParams}",
            f"【模型执行主提示词】{group.videoPrompt}",
            f"【禁止项】{group.negativePrompt}",
        ]
    )


def pack_video_plan_items(
    items: list[VideoProductionPlanItem],
) -> list[list[VideoProductionPlanItem]]:
    ordered = sorted(items, key=lambda item: (item.episodeNumber, item.groupIndex))
    batches: list[list[VideoProductionPlanItem]] = []
    for item in ordered:
        current = batches[-1] if batches else []
        previous = current[-1] if current else None
        current_seconds = sum(part.durationSeconds for part in current)
        can_append = bool(
            previous
            and item.episodeNumber == previous.episodeNumber
            and item.groupIndex == previous.groupIndex + 1
            and item.aspectRatio == previous.aspectRatio
            and item.targetModel == previous.targetModel
            and current_seconds + item.durationSeconds <= VIDEO_REQUEST_SECONDS
        )
        if can_append:
            current.append(item)
        else:
            batches.append([item])
    return batches


def build_video_batch_prompt(items: list[VideoProductionPlanItem]) -> str:
    cursor = 0
    sections = [
        "【任务参数】BD Seedance2.5，30秒，写实电影质感。",
        "【全局连续性硬锁】严格按以下时间轴执行；各段人物身份、五官、年龄、体态、服装、发型、伤势、道具、场景结构、主光方向、站位与运动方向连续，不得重复前段剧情，不得越轴。动作遵守重力、惯性、接触与受力反馈。",
    ]
    for item in items:
        end = cursor + item.durationSeconds
        sections.append(
            f"【{cursor:02d}-{end:02d}秒｜第{item.episodeNumber}集·镜头组{item.groupIndex}】\n"
            f"叙事目的：{item.purpose}\n{item.prompt}"
        )
        cursor = end
    if cursor < VIDEO_REQUEST_SECONDS:
        sections.append(
            f"【{cursor:02d}-{VIDEO_REQUEST_SECONDS:02d}秒｜自然收束】\n"
            "延续最后一个镜头的动作和情绪，让表演、环境声与镜头运动自然收束；不新增人物、事件或台词。"
        )
    sections.append(
        "【终帧连续性】30秒终帧保持最后一段人物位置、朝向、姿态、表情、服装、伤势、手中物、场景结构和光线，形成可供下一条视频直接顺接的稳定构图。"
    )
    return "\n\n".join(sections)


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
        if item.status == "confirmed":
            required_values = (
                (item.referencePrompt,)
                if is_collective_character(item.kind, item.name)
                else (
                    item.description,
                    item.visualAnchor,
                    item.continuityNotes,
                    item.referencePrompt,
                )
            )
            if any(not value.strip() for value in required_values):
                raise ValueError(
                    f"{item.name} 尚未补全说明、视觉锚点、连续性或生图提示词"
                )


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
    asset_tunnel_service: TemporaryAssetTunnel | None = None,
) -> FastAPI:
    resolved_data_dir = data_dir or Path(
        os.environ.get("MINGYAN_DATA_DIR", Path.home() / ".mingyan-ai")
    )
    database_path = resolved_data_dir / "mingyan.sqlite3"
    credentials = credential_store or SystemCredentialStore()
    asset_tunnel = asset_tunnel_service or TemporaryAssetTunnel(resolved_data_dir)

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
            connection.execute(
                """
                UPDATE video_generation_jobs
                SET status = 'interrupted',
                    error = '本地服务曾在视频任务执行期间停止；已有服务商任务号时将只恢复查询。',
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (utc_now(),),
            )
        try:
            yield
        finally:
            asset_tunnel.stop()

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

    def video_model_settings() -> VideoModelSettingsOut:
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM model_settings WHERE kind = ?", ("video",)
            ).fetchone()
        try:
            has_credential = bool(credentials.get("video-model-api-key"))
        except KeyringError as error:
            raise HTTPException(
                status_code=503, detail="无法访问系统凭据库，请检查系统钥匙串服务"
            ) from error
        base_url = row["base_url"] if row else ""
        model = row["model"] if row else ""
        return VideoModelSettingsOut(
            provider="shuikule-openai-compatible",
            baseUrl=base_url,
            model=model,
            hasCredential=has_credential,
            configured=bool(base_url and model and has_credential),
            updatedAt=row["updated_at"] if row else None,
        )

    def video_model_credentials() -> tuple[VideoModelSettingsOut, str]:
        settings = video_model_settings()
        if not settings.configured:
            raise HTTPException(status_code=409, detail="请先保存完整的视频模型配置")
        try:
            api_key = credentials.get("video-model-api-key")
        except KeyringError as error:
            raise HTTPException(
                status_code=503, detail="无法访问系统凭据库，请检查系统钥匙串服务"
            ) from error
        if not api_key:
            raise HTTPException(status_code=409, detail="系统凭据库中没有找到视频 API 密钥")
        return settings, api_key

    def asset_tunnel_status() -> AssetTunnelStatusOut:
        status = asset_tunnel.status()
        return AssetTunnelStatusOut(
            provider="cloudflare-quick-tunnel",
            installed=status.installed,
            running=status.running,
            projectId=status.project_id,
            publicUrl=status.public_url,
            exposedAssetCount=status.exposed_asset_count,
            error=status.error,
            warning=(
                "临时地址只用于当前视频任务；任何持有完整随机链接的人都能读取已开放素材。"
                "任务结束后请立即关闭通道。"
            ),
        )

    def asset_reference_file_path(
        project_id: str, asset_id: str, image_id: str
    ) -> Path | None:
        image_dir = resolved_data_dir / "generated" / project_id / asset_id
        return next(
            (
                path
                for suffix in (".png", ".jpg", ".jpeg", ".webp")
                if (path := image_dir / f"{image_id}{suffix}").is_file()
            ),
            None,
        )

    def asset_identity_master_file_path(
        project_id: str, asset_id: str, master_id: str
    ) -> Path | None:
        image_dir = resolved_data_dir / "generated" / project_id / asset_id
        return next(
            (
                path
                for suffix in (".png", ".jpg", ".jpeg", ".webp")
                if (path := image_dir / f"identity-{master_id}{suffix}").is_file()
            ),
            None,
        )

    def identity_reference_for_asset(
        project_id: str, asset: AssetItem
    ) -> tuple[str, str]:
        if (
            asset.kind != "character"
            or is_collective_character(asset.kind, asset.name)
        ):
            return "", ""
        if not asset.referenceImages:
            return "", ""
        if not asset.identityMasterId:
            raise HTTPException(
                status_code=409,
                detail=f"请先为{asset.name}建立单张正脸身份母版，再生成后续版本",
            )
        reference = next(
            (
                master
                for master in asset.identityMasters
                if master.id == asset.identityMasterId
            ),
            None,
        )
        if reference is None:
            raise HTTPException(status_code=409, detail=f"{asset.name} 的身份母版记录无效")
        image_path = asset_identity_master_file_path(
            project_id, asset.id, reference.id
        )
        if image_path is None:
            raise HTTPException(
                status_code=409,
                detail=f"{asset.name} 的身份母版文件缺失，无法执行身份硬控",
            )
        suffix_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        image_bytes = image_path.read_bytes()
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=409,
                detail=f"{asset.name} 的身份母版为空或超过 10MB",
            )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        mime_type = suffix_mime[image_path.suffix.lower()]
        return f"data:{mime_type};base64,{encoded}", reference.id

    def generation_request_for_asset(
        project_id: str, asset: AssetItem, base_prompt: str
    ) -> tuple[str, dict[str, list[str]], str]:
        reference_data_uri, reference_id = identity_reference_for_asset(
            project_id, asset
        )
        if not reference_id:
            return base_prompt, {}, ""
        identity_lock = (
            "【单一身份母版硬锁｜最高优先级】图1只包含一个人的正脸，必须把该面部作为唯一身份基准。"
            "必须保留同一张脸、骨相、五官比例、年龄、肤色和身体比例；只允许按照本次提示更换服装、"
            "配饰、发型、妆容与剧情状态。禁止重新选角，禁止生成相似但不同的人，禁止让文字描述覆盖身份母版。"
        )
        return (
            f"{identity_lock}\n\n{base_prompt}",
            {"images": [reference_data_uri]},
            reference_id,
        )

    def state_image_prompt(asset: AssetItem, request: AssetImageGenerateRequest) -> str:
        if not request.stateLabel or not request.statePrompt:
            raise HTTPException(status_code=422, detail="剧情状态名称和状态描述不能为空")
        return (
            f"定向生成人物 {asset.name} 的剧情状态图：{request.stateLabel}。\n\n"
            f"CHANGE：仅将服装、发型、配饰、妆容、伤势、表情与姿态调整为：{request.statePrompt}\n\n"
            "PRESERVE EXACTLY：图1身份母版中的脸、骨相、五官间距、眼型、鼻型、唇形、年龄、"
            "肤色与人物辨识度必须完全一致。生成单张真人摄影画面，只出现同一个人物；采用中性影棚背景，"
            "人物从头到脚完整入镜，正面或轻微四分之三角度，面部清晰可辨。\n\n"
            "ONLY CHANGE：上述剧情状态。不得输出四宫格、拼图、多人、多张脸、文字、标签或资产卡排版。"
        )

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
            with connect(database_path) as connection:
                asset_row = connection.execute(
                    "SELECT * FROM project_assets WHERE project_id = ?",
                    (job["project_id"],),
                ).fetchone()
            if asset_row is None:
                raise HTTPException(status_code=404, detail="资产库不存在")
            job_library = AssetLibraryPayload.model_validate(
                json.loads(asset_row["payload"])
            )
            job_asset = next(
                (item for item in job_library.items if item.id == job["asset_id"]),
                None,
            )
            if job_asset is None:
                raise HTTPException(status_code=404, detail="资产不存在")
            if provider_task_id and not job_asset.identityMasterId:
                request_prompt = job["prompt"]
                reference_params: dict[str, list[str]] = {}
                identity_reference_id = ""
            else:
                request_prompt, reference_params, identity_reference_id = (
                    generation_request_for_asset(
                        job["project_id"], job_asset, job["prompt"]
                    )
                )
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
                            "prompt": request_prompt,
                            "params": {
                                "version": "flare",
                                "aspect_ratio": job["aspect_ratio"],
                                "resolution": "1K",
                                "quality": "auto",
                                "background": "opaque",
                                **reference_params,
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
                prompt=request_prompt,
                model=job["model"],
                taskId=provider_task_id,
                aspectRatio=job["aspect_ratio"],
                resolution="1K",
                cost=cost,
                identityReferenceImageId=identity_reference_id,
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

    def video_response_detail(response: httpx.Response, fallback: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            return fallback
        if not isinstance(payload, dict):
            return fallback
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or fallback)
        detail = payload.get("detail") or payload.get("message")
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        return str(error or detail or payload.get("fail_reason") or fallback)

    def process_video_job(job_id: str) -> None:
        with connect(database_path) as connection:
            job = connection.execute(
                "SELECT * FROM video_generation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if job is None or job["status"] != "running":
            return

        provider_task_id = job["provider_task_id"]
        recoverable = bool(provider_task_id)
        tunnel_started = False
        temporary_path: Path | None = None
        try:
            settings, api_key = video_model_credentials()
            api_root = settings.baseUrl.rstrip("/")
            headers = {"Authorization": f"Bearer {api_key}"}
            status_payload: dict = {}
            with httpx.Client(
                transport=model_transport,
                timeout=httpx.Timeout(60, connect=30),
                follow_redirects=True,
            ) as client:
                if not provider_task_id:
                    references = json.loads(job["reference_assets"])
                    files: dict[str, Path] = {}
                    for reference in references:
                        logical_id = str(reference["logicalId"])
                        if reference.get("role") == "identity":
                            image_path = asset_identity_master_file_path(
                                job["project_id"],
                                str(reference["assetId"]),
                                str(reference["imageId"]),
                            )
                        else:
                            image_path = asset_reference_file_path(
                                job["project_id"],
                                str(reference["assetId"]),
                                str(reference["imageId"]),
                            )
                        if image_path is None:
                            raise HTTPException(
                                status_code=409,
                                detail=f"{reference['name']} 的主参考图文件不存在",
                            )
                        files[logical_id] = image_path
                    reference_urls = asset_tunnel.start(job["project_id"], files)
                    tunnel_started = True
                    asset_tunnel.verify_urls(reference_urls)
                    ordered_urls = [
                        reference_urls[str(reference["logicalId"])]
                        for reference in references
                    ]
                    reference_guide_parts: list[str] = []
                    for index, reference in enumerate(references, start=1):
                        item_ids = reference.get("itemIds", [])
                        scope = f"（用于{'、'.join(item_ids)}）" if item_ids else ""
                        if reference.get("role") == "identity":
                            reference_guide_parts.append(
                                f"图{index}={reference['name']}·身份母版"
                                "（只锁定脸、骨相、年龄与人物身份，全片唯一）"
                            )
                        else:
                            reference_guide_parts.append(
                                f"图{index}={reference['name']}·镜头状态{scope}"
                            )
                    reference_guide = "；".join(reference_guide_parts)
                    created = client.post(
                        f"{api_root}/videos",
                        headers={**headers, "Content-Type": "application/json"},
                        json={
                            "model": job["model"],
                            "prompt": (
                                f"【参考图顺序锁定】{reference_guide}。"
                                "人物身份以身份母版为最高优先级；服装、发型、身体状态与情绪只读取对应镜头状态图；"
                                "场景以对应场景参考图为准；"
                                "同名人物跨镜头组必须保持同一身份，仅允许服装、发型、"
                                "身体状态和情绪变化。\n\n"
                                f"{job['prompt']}"
                            ),
                            "seconds": str(job["seconds"]),
                            "size": (
                                "1280x720"
                                if job["aspect_ratio"] == "16:9"
                                else "720x1280"
                            ),
                            "metadata": {
                                "__workbench_passthrough": {
                                    "aspect_ratio": job["aspect_ratio"],
                                    "resolution": "720p",
                                },
                                "__workbench_refs": {
                                    "reference_image_urls": ordered_urls,
                                    "reference_video_urls": [],
                                    "reference_audio_urls": [],
                                },
                            },
                        },
                    )
                    if not created.is_success:
                        raise HTTPException(
                            status_code=502,
                            detail=video_response_detail(
                                created,
                                f"视频服务创建任务失败（HTTP {created.status_code}）",
                            ),
                        )
                    try:
                        created_payload = created.json()
                    except ValueError as error:
                        raise HTTPException(
                            status_code=502, detail="视频服务返回了无法识别的任务数据"
                        ) from error
                    provider_task_id = str(
                        created_payload.get("id")
                        or created_payload.get("task_id")
                        or ""
                    )
                    if not provider_task_id:
                        raise HTTPException(status_code=502, detail="视频服务没有返回任务编号")
                    recoverable = True
                    with connect(database_path) as connection:
                        connection.execute(
                            """
                            UPDATE video_generation_jobs
                            SET provider_task_id = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (provider_task_id, utc_now(), job_id),
                        )

                deadline = time.monotonic() + 45 * 60
                while time.monotonic() < deadline:
                    status_response = client.get(
                        f"{api_root}/videos/{provider_task_id}", headers=headers
                    )
                    if not status_response.is_success:
                        raise HTTPException(
                            status_code=502,
                            detail=video_response_detail(
                                status_response,
                                f"视频任务查询失败（HTTP {status_response.status_code}）",
                            ),
                        )
                    try:
                        status_payload = status_response.json()
                    except ValueError as error:
                        raise HTTPException(
                            status_code=502, detail="视频任务状态无法识别"
                        ) from error
                    state = str(
                        status_payload.get("status")
                        or status_payload.get("state")
                        or ""
                    ).lower()
                    if state == "completed":
                        break
                    if state == "failed":
                        recoverable = False
                        failure = status_payload.get("error")
                        if isinstance(failure, dict):
                            failure = failure.get("message") or failure.get("code")
                        raise HTTPException(
                            status_code=502,
                            detail=str(
                                failure
                                or status_payload.get("fail_reason")
                                or "视频任务生成失败"
                            ),
                        )
                    time.sleep(5)
                else:
                    raise HTTPException(status_code=504, detail="视频任务等待超时，可稍后恢复查询")

                video_dir = resolved_data_dir / "generated" / job["project_id"] / "videos"
                video_dir.mkdir(parents=True, exist_ok=True)
                video_path = video_dir / f"{job_id}.mp4"
                temporary_path = video_dir / f".{job_id}.tmp"
                total_bytes = 0
                with client.stream(
                    "GET",
                    f"{api_root}/videos/{provider_task_id}/content",
                    headers=headers,
                ) as content_response:
                    if content_response.status_code not in {200, 206}:
                        raise HTTPException(
                            status_code=502,
                            detail=f"视频生成成功，但下载成品失败（HTTP {content_response.status_code}）",
                        )
                    content_type = content_response.headers.get(
                        "content-type", ""
                    ).split(";", 1)[0]
                    if content_type != "video/mp4":
                        raise HTTPException(
                            status_code=502, detail="视频服务返回的成品不是 MP4 文件"
                        )
                    with temporary_path.open("wb") as output:
                        for chunk in content_response.iter_bytes(512 * 1024):
                            if not chunk:
                                continue
                            total_bytes += len(chunk)
                            if total_bytes > 2 * 1024 * 1024 * 1024:
                                raise HTTPException(
                                    status_code=502, detail="视频成品超过 2GB 安全限制"
                                )
                            output.write(chunk)
                if total_bytes == 0:
                    raise HTTPException(status_code=502, detail="视频服务返回了空成品")
                temporary_path.replace(video_path)
                temporary_path = None

            raw_cost = status_payload.get("cost")
            cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else None
            now = utc_now()
            result_url = f"/api/projects/{job['project_id']}/videos/{job_id}/content"
            with connect(database_path) as connection:
                connection.execute(
                    """
                    UPDATE video_generation_jobs
                    SET status = 'completed', provider_task_id = ?, result_url = ?,
                        cost = ?, error = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (provider_task_id, result_url, cost, now, job_id),
                )
        except (
            HTTPException,
            httpx.RequestError,
            sqlite3.Error,
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
        ) as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if isinstance(error, HTTPException):
                message = str(error.detail)
            elif isinstance(error, httpx.RequestError):
                message = f"视频服务连接中断：{type(error).__name__}"
            else:
                message = str(error) or type(error).__name__
            if tunnel_started and "参考素材" in message:
                message = (
                    f"{message}（临时素材网关成功命中 "
                    f"{asset_tunnel.served_request_count()} 次）"
                )
            status = "interrupted" if recoverable else "failed"
            with connect(database_path) as connection:
                connection.execute(
                    """
                    UPDATE video_generation_jobs
                    SET status = ?, provider_task_id = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, provider_task_id, message, utc_now(), job_id),
                )
        finally:
            if tunnel_started:
                asset_tunnel.stop()

    def process_video_batch(batch_id: str) -> None:
        while True:
            with connect(database_path) as connection:
                running = connection.execute(
                    """
                    SELECT id FROM video_generation_jobs
                    WHERE batch_id = ? AND status = 'running'
                    """,
                    (batch_id,),
                ).fetchone()
                if running is not None:
                    return
                queued = connection.execute(
                    """
                    SELECT id FROM video_generation_jobs
                    WHERE batch_id = ? AND status = 'queued'
                    ORDER BY created_at, id LIMIT 1
                    """,
                    (batch_id,),
                ).fetchone()
                if queued is None:
                    return
                claimed = connection.execute(
                    """
                    UPDATE video_generation_jobs
                    SET status = 'running', error = '', updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (utc_now(), queued["id"]),
                )
            if claimed.rowcount:
                process_video_job(queued["id"])
                with connect(database_path) as connection:
                    saved = connection.execute(
                        "SELECT status FROM video_generation_jobs WHERE id = ?",
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

    @application.get("/api/settings/video-model", response_model=VideoModelSettingsOut)
    def get_video_model_settings() -> VideoModelSettingsOut:
        return video_model_settings()

    @application.put("/api/settings/video-model", response_model=VideoModelSettingsOut)
    def update_video_model_settings(
        payload: VideoModelSettingsUpdate,
    ) -> VideoModelSettingsOut:
        if payload.apiKey:
            try:
                credentials.set("video-model-api-key", payload.apiKey)
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
                ("video", payload.baseUrl, payload.model, now),
            )
        return video_model_settings()

    @application.post(
        "/api/settings/video-model/test", response_model=TextModelConnectionOut
    )
    def test_video_model_connection() -> TextModelConnectionOut:
        settings, api_key = video_model_credentials()
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
                status_code=502, detail=f"无法连接视频模型服务：{type(error).__name__}"
            ) from error

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=502, detail="视频模型服务拒绝鉴权，请检查 API 密钥")
        if not response.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"视频模型服务返回 HTTP {response.status_code}，请检查接口地址",
            )
        try:
            model_ids = {
                item.get("id")
                for item in response.json().get("data", [])
                if isinstance(item, dict)
            }
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=502, detail="视频模型服务返回了无法识别的数据") from error
        if settings.model not in model_ids:
            raise HTTPException(
                status_code=502,
                detail=f"鉴权成功，但模型列表中没有 {settings.model}",
            )
        return TextModelConnectionOut(
            connected=True,
            model=settings.model,
            latencyMs=latency_ms,
            message="鉴权成功，视频模型可用（未生成视频）",
        )

    @application.get(
        "/api/settings/asset-tunnel", response_model=AssetTunnelStatusOut
    )
    def get_asset_tunnel_status() -> AssetTunnelStatusOut:
        return asset_tunnel_status()

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

    def video_plan_inputs(
        project_id: str,
    ) -> tuple[list[sqlite3.Row], sqlite3.Row, sqlite3.Row | None]:
        with connect(database_path) as connection:
            project_row = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            screenplay_row = connection.execute(
                "SELECT * FROM project_screenplays WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            storyboard_rows = connection.execute(
                """
                SELECT * FROM project_storyboards
                WHERE project_id = ? ORDER BY episode_number
                """,
                (project_id,),
            ).fetchall()
            asset_row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            saved_plan = connection.execute(
                "SELECT * FROM video_production_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if project_row is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        if screenplay_row is None or screenplay_row["status"] != "approved":
            raise HTTPException(status_code=409, detail="请先完成人工确认剧本")
        if not storyboard_rows:
            raise HTTPException(status_code=409, detail="请先生成至少一集分镜")
        if any(
            row["screenplay_updated_at"] != screenplay_row["updated_at"]
            for row in storyboard_rows
        ):
            raise HTTPException(status_code=409, detail="剧本已更新，请重新生成分镜")
        if asset_row is None:
            raise HTTPException(status_code=409, detail="请先建立一致性资产库")
        return storyboard_rows, asset_row, saved_plan

    def selected_video_plan_items(project_id: str) -> list[VideoProductionPlanItem]:
        storyboard_rows, asset_row, saved_plan = video_plan_inputs(project_id)
        items, storyboard_updated_at, asset_library_updated_at = (
            build_video_plan_items(storyboard_rows, asset_row)
        )
        if (
            saved_plan is None
            or saved_plan["storyboard_updated_at"] != storyboard_updated_at
            or saved_plan["asset_library_updated_at"] != asset_library_updated_at
        ):
            raise HTTPException(status_code=409, detail="请先保存当前版本的视频生产清单")
        selection = VideoPlanSelectionPayload.model_validate(
            json.loads(saved_plan["payload"])
        )
        apply_video_reference_image_ids(items, selection.referenceImageIds)
        items_by_id = {item.id: item for item in items}
        selected_items = [
            items_by_id[item_id]
            for item_id in selection.selectedItemIds
            if item_id in items_by_id
        ]
        if not selected_items or len(selected_items) != len(selection.selectedItemIds):
            raise HTTPException(status_code=409, detail="视频生产清单为空或包含过期镜头组")
        if any(not item.ready for item in selected_items):
            raise HTTPException(status_code=409, detail="视频生产清单中仍有未就绪镜头组")
        return selected_items

    def video_reference_files(
        project_id: str, items: list[VideoProductionPlanItem]
    ) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for item in items:
            for reference in item.assetReferences:
                if reference.identityMasterId:
                    identity_logical_id = (
                        f"identity:{reference.assetId}:{reference.identityMasterId}"
                    )
                    if identity_logical_id not in files:
                        identity_path = asset_identity_master_file_path(
                            project_id,
                            reference.assetId,
                            reference.identityMasterId,
                        )
                        if identity_path is None:
                            raise HTTPException(
                                status_code=409,
                                detail=f"{reference.name} 的身份母版文件不存在",
                            )
                        files[identity_logical_id] = identity_path
                logical_id = f"{reference.assetId}:{reference.imageId}"
                if logical_id in files:
                    continue
                image_path = asset_reference_file_path(
                    project_id, reference.assetId, reference.imageId
                )
                if image_path is None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"{reference.name} 的主参考图文件不存在",
                    )
                files[logical_id] = image_path
        return files

    @application.get(
        "/api/projects/{project_id}/video-plan",
        response_model=VideoProductionPlanOut,
    )
    def get_video_production_plan(project_id: str) -> VideoProductionPlanOut:
        storyboard_rows, asset_row, saved_plan = video_plan_inputs(project_id)
        items, storyboard_updated_at, asset_library_updated_at = (
            build_video_plan_items(storyboard_rows, asset_row)
        )
        current = bool(
            saved_plan
            and saved_plan["storyboard_updated_at"] == storyboard_updated_at
            and saved_plan["asset_library_updated_at"] == asset_library_updated_at
        )
        selection = (
            VideoPlanSelectionPayload.model_validate(json.loads(saved_plan["payload"]))
            if saved_plan
            else VideoPlanSelectionPayload(selectedItemIds=[])
        )
        apply_video_reference_image_ids(items, selection.referenceImageIds)
        item_ids = {item.id for item in items}
        return VideoProductionPlanOut(
            projectId=project_id,
            items=items,
            selectedItemIds=[
                item_id for item_id in selection.selectedItemIds if item_id in item_ids
            ],
            referenceImageIds=selection.referenceImageIds,
            storyboardUpdatedAt=storyboard_updated_at,
            assetLibraryUpdatedAt=asset_library_updated_at,
            current=current,
            confirmedAt=saved_plan["updated_at"] if saved_plan else None,
        )

    @application.post(
        "/api/projects/{project_id}/video-plan",
        response_model=VideoProductionPlanOut,
    )
    def confirm_video_production_plan(
        project_id: str, payload: VideoPlanConfirm
    ) -> VideoProductionPlanOut:
        storyboard_rows, asset_row, _ = video_plan_inputs(project_id)
        items, storyboard_updated_at, asset_library_updated_at = (
            build_video_plan_items(storyboard_rows, asset_row)
        )
        items_by_id = {item.id: item for item in items}
        if any(item_id not in payload.itemIds for item_id in payload.referenceImageIds):
            raise HTTPException(
                status_code=422, detail="状态参考图只能为本次选中的镜头组设置"
            )
        for item_id in payload.itemIds:
            item = items_by_id.get(item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="生产清单包含不存在的镜头组")
            if not item.ready:
                raise HTTPException(
                    status_code=409,
                    detail=f"第 {item.episodeNumber} 集镜头组 {item.groupIndex} 尚未就绪",
                )
            references_by_asset = {
                reference.assetId: reference for reference in item.assetReferences
            }
            for asset_id, image_id in payload.referenceImageIds.get(
                item_id, {}
            ).items():
                reference = references_by_asset.get(asset_id)
                if reference is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"镜头组 {item.groupIndex} 不包含所选资产",
                    )
                if image_id not in {
                    image.id for image in reference.availableImages
                }:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{reference.name} 的状态参考图无效",
                    )
        now = utc_now()
        selection = VideoPlanSelectionPayload(
            selectedItemIds=payload.itemIds,
            referenceImageIds=payload.referenceImageIds,
        )
        apply_video_reference_image_ids(items, selection.referenceImageIds)
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO video_production_plans (
                    project_id, payload, storyboard_updated_at,
                    asset_library_updated_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    payload = excluded.payload,
                    storyboard_updated_at = excluded.storyboard_updated_at,
                    asset_library_updated_at = excluded.asset_library_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    selection.model_dump_json(),
                    storyboard_updated_at,
                    asset_library_updated_at,
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET stage = 'video', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return VideoProductionPlanOut(
            projectId=project_id,
            items=items,
            selectedItemIds=payload.itemIds,
            referenceImageIds=payload.referenceImageIds,
            storyboardUpdatedAt=storyboard_updated_at,
            assetLibraryUpdatedAt=asset_library_updated_at,
            current=True,
            confirmedAt=now,
        )

    @application.post(
        "/api/projects/{project_id}/video-plan/queue",
        response_model=list[ProjectTaskOut],
    )
    def queue_video_production_plan(
        project_id: str, background_tasks: BackgroundTasks
    ) -> list[ProjectTaskOut]:
        settings, _ = video_model_credentials()
        if asset_tunnel.cloudflared_path() is None:
            raise HTTPException(
                status_code=409, detail="尚未安装 cloudflared，无法提交本地参考素材"
            )
        tunnel_status = asset_tunnel.status()
        if tunnel_status.running and tunnel_status.project_id != project_id:
            raise HTTPException(status_code=409, detail="临时通道正在被其他项目使用")
        selected_items = selected_video_plan_items(project_id)
        video_reference_files(project_id, selected_items)
        with connect(database_path) as connection:
            active = connection.execute(
                """
                SELECT id FROM video_generation_jobs
                WHERE status IN ('queued', 'running', 'interrupted')
                LIMIT 1
                """
            ).fetchone()
        if active is not None:
            raise HTTPException(
                status_code=409, detail="已有未完成的视频任务，请先在任务中心处理"
            )

        batch_id = str(uuid4())
        video_batches = pack_video_plan_items(selected_items)
        with connect(database_path) as connection:
            for items in video_batches:
                now = utc_now()
                references_by_id: dict[str, dict[str, object]] = {}
                for item in items:
                    for reference in item.assetReferences:
                        if reference.identityMasterId:
                            identity_logical_id = (
                                f"identity:{reference.assetId}:"
                                f"{reference.identityMasterId}"
                            )
                            identity_reference = references_by_id.setdefault(
                                identity_logical_id,
                                {
                                    "logicalId": identity_logical_id,
                                    "assetId": reference.assetId,
                                    "imageId": reference.identityMasterId,
                                    "name": reference.name,
                                    "role": "identity",
                                    "itemIds": [],
                                },
                            )
                            identity_item_ids = identity_reference["itemIds"]
                            if (
                                isinstance(identity_item_ids, list)
                                and item.id not in identity_item_ids
                            ):
                                identity_item_ids.append(item.id)
                        logical_id = f"{reference.assetId}:{reference.imageId}"
                        saved_reference = references_by_id.setdefault(
                            logical_id,
                            {
                                "logicalId": logical_id,
                                "assetId": reference.assetId,
                                "imageId": reference.imageId,
                                "name": reference.name,
                                "role": "state",
                                "itemIds": [],
                            },
                        )
                        item_ids = saved_reference["itemIds"]
                        if isinstance(item_ids, list) and item.id not in item_ids:
                            item_ids.append(item.id)
                references = list(references_by_id.values())
                first_item = items[0]
                last_item = items[-1]
                group_label = (
                    str(first_item.groupIndex)
                    if len(items) == 1
                    else f"{first_item.groupIndex}–{last_item.groupIndex}"
                )
                connection.execute(
                    """
                    INSERT INTO video_generation_jobs (
                        id, project_id, batch_id, plan_item_id, title, prompt,
                        seconds, aspect_ratio, reference_assets, model, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        str(uuid4()),
                        project_id,
                        batch_id,
                        "+".join(item.id for item in items),
                        f"第 {first_item.episodeNumber} 集 · 镜头组 {group_label}（30秒）",
                        build_video_batch_prompt(items),
                        VIDEO_REQUEST_SECONDS,
                        first_item.aspectRatio,
                        json.dumps(references, ensure_ascii=False),
                        settings.model,
                        now,
                        now,
                    ),
                )
            rows = connection.execute(
                """
                SELECT * FROM video_generation_jobs
                WHERE batch_id = ? ORDER BY created_at, id
                """,
                (batch_id,),
            ).fetchall()
        background_tasks.add_task(process_video_batch, batch_id)
        return [row_to_video_generation_task(row) for row in rows]

    @application.post(
        "/api/projects/{project_id}/asset-tunnel",
        response_model=AssetTunnelStatusOut,
    )
    def start_asset_tunnel(project_id: str) -> AssetTunnelStatusOut:
        selected_items = selected_video_plan_items(project_id)
        files = video_reference_files(project_id, selected_items)
        try:
            asset_tunnel.start(project_id, files)
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=409,
                detail="尚未安装 cloudflared，无法开启临时公网通道",
            ) from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return asset_tunnel_status()

    @application.delete(
        "/api/projects/{project_id}/asset-tunnel",
        response_model=AssetTunnelStatusOut,
    )
    def stop_asset_tunnel(project_id: str) -> AssetTunnelStatusOut:
        status = asset_tunnel.status()
        if status.running and status.project_id != project_id:
            raise HTTPException(status_code=409, detail="临时通道正在被其他项目使用")
        asset_tunnel.stop()
        return asset_tunnel_status()

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
                        library.standard.visualStandard, item.kind, item.name
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
            if (
                asset.kind == "character"
                and not is_collective_character(asset.kind, asset.name)
                and asset.referenceImages
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"{asset.name} 已有资产卡，后续版本请使用剧情状态图生成",
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
            video_rows = connection.execute(
                """
                SELECT * FROM video_generation_jobs
                WHERE project_id = ? ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        jobs = [row_to_generation_task(row) for row in job_rows]
        video_jobs = [row_to_video_generation_task(row) for row in video_rows]
        job_ids = {task.id for task in jobs}
        legacy = [
            task
            for task in (asset_library_tasks(asset_row) if asset_row else [])
            if task.id not in job_ids
        ]
        return sorted(
            [*video_jobs, *jobs, *legacy],
            key=lambda task: task.createdAt,
            reverse=True,
        )

    @application.post(
        "/api/projects/{project_id}/tasks/{task_id}/retry",
        response_model=ProjectTaskOut,
    )
    def retry_generation_task(
        project_id: str, task_id: str, background_tasks: BackgroundTasks
    ) -> ProjectTaskOut:
        with connect(database_path) as connection:
            image_row = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE id = ? AND project_id = ?
                """,
                (task_id, project_id),
            ).fetchone()
            video_row = (
                connection.execute(
                    """
                    SELECT * FROM video_generation_jobs
                    WHERE id = ? AND project_id = ?
                    """,
                    (task_id, project_id),
                ).fetchone()
                if image_row is None
                else None
            )
            row = image_row or video_row
            if row is None:
                raise HTTPException(status_code=404, detail="生成任务不存在")
            if row["status"] != "failed":
                raise HTTPException(status_code=409, detail="只有失败任务可以重新生成")
            if image_row is not None:
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
            else:
                connection.execute(
                    """
                    UPDATE video_generation_jobs
                    SET status = 'queued', provider_task_id = '', result_url = '',
                        cost = NULL, error = '', attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (utc_now(), task_id),
                )
                saved = connection.execute(
                    "SELECT * FROM video_generation_jobs WHERE id = ?", (task_id,)
                ).fetchone()
        if image_row is not None:
            background_tasks.add_task(process_generation_batch, row["batch_id"])
            return row_to_generation_task(saved)
        background_tasks.add_task(process_video_batch, row["batch_id"])
        return row_to_video_generation_task(saved)

    @application.post(
        "/api/projects/{project_id}/tasks/resume",
        response_model=list[ProjectTaskOut],
    )
    def resume_generation_tasks(
        project_id: str, background_tasks: BackgroundTasks
    ) -> list[ProjectTaskOut]:
        with connect(database_path) as connection:
            image_rows = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE project_id = ? AND status IN ('queued', 'interrupted')
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
            video_rows = connection.execute(
                """
                SELECT * FROM video_generation_jobs
                WHERE project_id = ? AND status IN ('queued', 'interrupted')
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
            if not image_rows and not video_rows:
                raise HTTPException(status_code=409, detail="没有可恢复的生成任务")
            connection.execute(
                """
                UPDATE asset_generation_jobs
                SET status = 'queued', error = '', updated_at = ?
                WHERE project_id = ? AND status = 'interrupted'
                """,
                (utc_now(), project_id),
            )
            connection.execute(
                """
                UPDATE video_generation_jobs
                SET status = 'queued', error = '', updated_at = ?
                WHERE project_id = ? AND status = 'interrupted'
                """,
                (utc_now(), project_id),
            )
            saved_images = connection.execute(
                """
                SELECT * FROM asset_generation_jobs
                WHERE project_id = ? AND status = 'queued'
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
            saved_videos = connection.execute(
                """
                SELECT * FROM video_generation_jobs
                WHERE project_id = ? AND status = 'queued'
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
        for batch_id in dict.fromkeys(row["batch_id"] for row in saved_images):
            background_tasks.add_task(process_generation_batch, batch_id)
        for batch_id in dict.fromkeys(row["batch_id"] for row in saved_videos):
            background_tasks.add_task(process_video_batch, batch_id)
        return [
            *[row_to_generation_task(row) for row in saved_images],
            *[row_to_video_generation_task(row) for row in saved_videos],
        ]

    @application.get(
        "/api/projects/{project_id}/assets/{asset_id}/identity-masters/{master_id}"
    )
    def get_asset_identity_master(
        project_id: str, asset_id: str, master_id: str
    ) -> FileResponse:
        try:
            UUID(project_id)
            UUID(asset_id)
            UUID(master_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="身份母版不存在") from error
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="资产库不存在")
        library = AssetLibraryPayload.model_validate(json.loads(row["payload"]))
        asset = next((item for item in library.items if item.id == asset_id), None)
        if asset is None or not any(
            master.id == master_id for master in asset.identityMasters
        ):
            raise HTTPException(status_code=404, detail="身份母版不存在")
        image_path = asset_identity_master_file_path(project_id, asset_id, master_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="本地身份母版文件不存在")
        return FileResponse(image_path)

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

    @application.get("/api/projects/{project_id}/videos/{task_id}/content")
    def get_generated_video(project_id: str, task_id: str) -> FileResponse:
        try:
            UUID(project_id)
            UUID(task_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="视频成品不存在") from error
        with connect(database_path) as connection:
            row = connection.execute(
                """
                SELECT status FROM video_generation_jobs
                WHERE id = ? AND project_id = ?
                """,
                (task_id, project_id),
            ).fetchone()
        if row is None or row["status"] != "completed":
            raise HTTPException(status_code=404, detail="视频成品不存在")
        video_path = (
            resolved_data_dir
            / "generated"
            / project_id
            / "videos"
            / f"{task_id}.mp4"
        )
        if not video_path.is_file():
            raise HTTPException(status_code=404, detail="本地视频文件不存在")
        return FileResponse(video_path, media_type="video/mp4")

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
        "/api/projects/{project_id}/assets/{asset_id}/identity-masters",
        response_model=AssetLibraryOut,
    )
    def create_asset_identity_master(
        project_id: str,
        asset_id: str,
        request: AssetIdentityMasterCreate,
    ) -> AssetLibraryOut:
        try:
            UUID(project_id)
            UUID(asset_id)
            UUID(request.sourceImageId)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="角色参考图不存在") from error
        with connect(database_path) as connection:
            row = connection.execute(
                "SELECT * FROM project_assets WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="资产库不存在")
        library = AssetLibraryPayload.model_validate(json.loads(row["payload"]))
        asset = next((item for item in library.items if item.id == asset_id), None)
        if asset is None:
            raise HTTPException(status_code=404, detail="角色不存在")
        if asset.kind != "character" or is_collective_character(asset.kind, asset.name):
            raise HTTPException(status_code=409, detail="身份母版只适用于单人角色")
        if not any(
            image.id == request.sourceImageId for image in asset.referenceImages
        ):
            raise HTTPException(status_code=404, detail="身份母版来源图不存在")

        matched = re.fullmatch(
            r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)",
            request.imageData,
        )
        if matched is None:
            raise HTTPException(status_code=422, detail="身份母版必须是 PNG、JPEG 或 WebP 图片")
        mime_type, encoded = matched.groups()
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(status_code=422, detail="身份母版图片数据无效") from error
        signatures = {
            "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
            "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
            "image/webp": (b"RIFF", ".webp"),
        }
        signature, suffix = signatures[mime_type]
        if (
            not image_bytes.startswith(signature)
            or not image_bytes
            or len(image_bytes) > 10 * 1024 * 1024
        ):
            raise HTTPException(status_code=422, detail="身份母版图片为空、格式错误或超过 10MB")

        now = utc_now()
        master_id = str(uuid4())
        image_dir = resolved_data_dir / "generated" / project_id / asset_id
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"identity-{master_id}{suffix}"
        temporary_path = image_dir / f".identity-{master_id}.tmp"
        temporary_path.write_bytes(image_bytes)
        temporary_path.replace(image_path)
        master = AssetIdentityMaster(
            id=master_id,
            url=(
                f"/api/projects/{project_id}/assets/{asset_id}/"
                f"identity-masters/{master_id}"
            ),
            sourceImageId=request.sourceImageId,
            createdAt=now,
        )
        updated_library = library.model_copy(
            update={
                "items": [
                    item.model_copy(
                        update={
                            "identityMasters": [*item.identityMasters, master],
                            "identityMasterId": master.id,
                        }
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

    @application.post(
        "/api/projects/{project_id}/assets/{asset_id}/images",
        response_model=AssetLibraryOut,
    )
    def generate_asset_reference_image(
        project_id: str,
        asset_id: str,
        request: AssetImageGenerateRequest | None = None,
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

        generation_request = request or AssetImageGenerateRequest()
        if (
            generation_request.mode == "asset-card"
            and asset.kind == "character"
            and not is_collective_character(asset.kind, asset.name)
            and asset.referenceImages
        ):
            raise HTTPException(
                status_code=409,
                detail="单人角色只生成一张初始资产卡，后续必须从身份母版生成剧情状态图",
            )
        if generation_request.mode == "state":
            if asset.kind != "character" or is_collective_character(
                asset.kind, asset.name
            ):
                raise HTTPException(status_code=409, detail="剧情状态图只适用于单人角色")
            base_prompt = state_image_prompt(asset, generation_request)
        else:
            base_prompt = asset.referencePrompt

        settings, api_key = image_model_credentials()
        aspect_ratio = asset_aspect_ratio(
            library.standard.visualStandard, asset.kind, asset.name
        )
        request_prompt, reference_params, identity_reference_id = (
            generation_request_for_asset(project_id, asset, base_prompt)
        )
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
                        "prompt": request_prompt,
                        "params": {
                            "version": "flare",
                            "aspect_ratio": aspect_ratio,
                            "resolution": "1K",
                            "quality": "auto",
                            "background": "opaque",
                            **reference_params,
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
            prompt=request_prompt,
            model=settings.model,
            taskId=task_id,
            aspectRatio=aspect_ratio,
            resolution="1K",
            cost=cost,
            identityReferenceImageId=identity_reference_id,
            role=generation_request.mode,
            stateLabel=(
                generation_request.stateLabel
                if generation_request.mode == "state"
                else ""
            ),
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
