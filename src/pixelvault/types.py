from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

import sys

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:  # pragma: no cover
    from typing_extensions import NotRequired


class Image(TypedDict):
    id: str
    url: str
    mime_type: str
    size: int
    width: Optional[int]
    height: Optional[int]
    filename: str
    folder: Optional[str]
    created_at: str
    #: Custom metadata set at upload or via ``images.update_metadata``; ``None`` when unset.
    metadata: NotRequired[Optional[Dict[str, Any]]]
    #: AI description from ``upload(describe=True)``: ``{"status": "pending" | "done" | "failed",
    #: "alt", "caption", "ocr_text", ...}``. ``None`` when never described. The text is untrusted
    #: model output derived from the image: escape it before rendering.
    description: NotRequired[Optional[Dict[str, Any]]]
    #: ``describe=True`` was requested but no description was started (quota, type, busy, ...).
    describe_skipped: NotRequired[str]
    #: Keyed public raster images: the same image as WebP/AVIF, usually far smaller.
    optimized_url: NotRequired[str]
    #: Present only on auto-expiring uploads.
    expires_in: NotRequired[int]
    temporary: NotRequired[bool]


class Generation(TypedDict):
    """What an ``images.generate`` call cost."""

    model: str
    credits_charged: int
    #: Credits left this month (they reset on the 1st, UTC).
    credits_remaining: int


class GeneratedImage(Image):
    generation: Generation


class ListMeta(TypedDict):
    total: int
    page: int
    per_page: int


class ImagePage(TypedDict):
    data: List[Image]
    meta: ListMeta


class SignedUrl(TypedDict):
    url: str
    expires: int


class UsageCounts(TypedDict):
    storage_bytes: int
    uploads: int


class UsageLimits(TypedDict):
    storage_bytes: int
    uploads_per_month: int
    bandwidth_bytes_per_month: int
    transforms_per_month: NotRequired[int]


class BandwidthUsage(TypedDict):
    """CDN bandwidth preflight. Null values are unknown/not applicable, never zero."""

    status: Literal["available", "unavailable", "unlimited"]
    used: Optional[int]
    remaining: Optional[int]
    limit: Optional[int]
    unit: Literal["bytes"]
    accounting_period: str
    resets_at: str
    measured_at: Optional[str]
    freshness: Literal["near_real_time", "delayed", "unavailable", "not_applicable"]


class GenerationUsage(TypedDict):
    credits_used: int
    credits_limit: int
    credits_remaining: int

class VideoSecondsUsage(TypedDict):
    seconds_used: int
    seconds_limit: int
    seconds_remaining: int


class Usage(TypedDict):
    plan: str
    period: str
    resets_at: str
    usage: UsageCounts
    limits: UsageLimits
    remaining: UsageCounts
    #: AI image-generation credits for the month (images.generate).
    generation: NotRequired[GenerationUsage]
    editing: NotRequired[GenerationUsage]
    bandwidth: NotRequired[BandwidthUsage]
    video_optimization: NotRequired[VideoSecondsUsage]
    video_enrichment: NotRequired[VideoSecondsUsage]


class ApiKey(TypedDict):
    id: str
    type: str
    environment: str
    label: Optional[str]
    key_prefix: str
    allowed_origins: Optional[List[str]]
    created_at: str
    last_used_at: Optional[str]
    #: True for the key that authenticated this request.
    current: bool


class CreatedKey(TypedDict):
    id: str
    #: The raw key. Shown only in this response.
    api_key: str
    type: str
    environment: str
    label: Optional[str]
    created_at: str


class DeviceLoginResult(TypedDict):
    account_id: str
    key_id: str
    api_key: str
    project_id: str
    email: str
    email_verified: bool


# Registration and batch responses are passed through as plain dicts.
JsonDict = Dict[str, Any]


class Video(TypedDict):
    id: str
    kind: str
    url: str
    original_url: str
    visibility: str
    mime_type: str
    size: int
    width: Optional[int]
    height: Optional[int]
    duration_seconds: Optional[float]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    has_audio: Optional[bool]
    fast_start: Optional[bool]
    social_compatible: Optional[bool]
    compatibility_warnings: List[Dict[str, Any]]
    social_optimization: Dict[str, Any]
    enrichment: Dict[str, Any]
    filename: str
    folder: Optional[str]
    collection_id: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: str
    social_ready_url: NotRequired[str]
    poster_url: NotRequired[str]
    expires_at: NotRequired[str]
    temporary: NotRequired[bool]
    replayed: NotRequired[bool]
    signed_expires: NotRequired[int]


class VideoPage(TypedDict):
    data: List[Video]
    meta: ListMeta


AudioEnrichmentStatus = Literal["not_requested", "pending", "processing", "complete", "failed"]


class AudioTranscript(TypedDict):
    status: Literal["complete"]
    text_url: NotRequired[str]
    vtt_url: NotRequired[str]
    segments_url: NotRequired[str]
    language: NotRequired[Optional[str]]
    languages: NotRequired[List[str]]
    model: NotRequired[Optional[str]]
    segment_count: NotRequired[int]


class AudioEnrichment(TypedDict):
    status: AudioEnrichmentStatus
    job_id: NotRequired[str]
    requested_at: NotRequired[str]
    completed_at: NotRequired[Optional[str]]
    transcript: NotRequired[Optional[AudioTranscript]]
    error: NotRequired[Dict[str, str]]


class Audio(TypedDict):
    id: str
    kind: Literal["audio"]
    url: str
    original_url: str
    visibility: Literal["public", "private"]
    mime_type: Literal["audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg"]
    size: int
    container: Literal["mp3", "wav", "m4a", "ogg"]
    codec: Literal["mp3", "pcm", "pcm_float", "aac", "opus", "vorbis"]
    duration_seconds: float
    sample_rate: int
    channels: int
    filename: str
    folder: Optional[str]
    collection_id: Optional[str]
    metadata: Optional[Dict[str, Any]]
    enrichment: AudioEnrichment
    created_at: str
    expires_at: NotRequired[str]
    temporary: NotRequired[bool]
    signed_expires: NotRequired[int]
    replayed: NotRequired[bool]


class AudioPage(TypedDict):
    data: List[Audio]
    meta: ListMeta


class AudioSignedUrl(TypedDict):
    url: str
    original_url: str
    expires: int
    visibility: Literal["public", "private"]
    enrichment: AudioEnrichment


class AudioWaitResult(TypedDict):
    audio: Audio
    status: AudioEnrichmentStatus
    timed_out: bool


class VideoUploadSession(TypedDict):
    upload_id: str
    asset_id: str
    part_size: int
    size: int
    visibility: str
    expires_at: str
    asset_expires_at: NotRequired[str]
    replayed: NotRequired[bool]
    completed: NotRequired[bool]
    asset: NotRequired[Video]


class VideoUploadedPart(TypedDict):
    part_number: int
    etag: str
    received: int
    replayed: NotRequired[bool]


class VideoWaitResult(TypedDict):
    video: Video
    status: str
    timed_out: bool


class ExportStart(TypedDict):
    job_id: str
    status: str
    image_count: int
    video_count: int
    audio_count: int
    asset_count: int
    status_url: str


class ExportJob(TypedDict):
    id: str
    status: str
    image_count: int
    video_count: int
    audio_count: int
    asset_count: int
    processed_count: int
    bytes: int
    created_at: str
    expires_at: str
    download_url: NotRequired[str]
    error: NotRequired[str]


class ExportWaitResult(TypedDict):
    job: ExportJob
    timed_out: bool


class VideoSignedUrls(TypedDict):
    url: str
    enrichment: Dict[str, Any]
    expires: int
    poster_url: NotRequired[str]
    social_url: NotRequired[str]
