"""Fail when the live API gains an operation this SDK neither wraps nor ignores.

Run in CI on every push and weekly, so an API change turns this repo red
until someone decides whether the SDK should cover it.
"""

import json
import sys
import urllib.request

COVERED = {
    "upload_image", "generate_image", "batch_upload", "list_images", "get_image", "update_image_metadata",
    "delete_image", "sign_image_url", "get_usage", "list_keys", "create_key", "revoke_key",
    "register_account", "device_login_start", "device_login_complete",
    "list_videos", "upload_video", "get_video", "delete_video", "update_video", "optimize_video",
    "enrich_video", "analyze_video", "generate_video_poster", "sign_video_url",
    "upload_audio", "list_audio", "get_audio", "update_audio", "sign_audio_url", "delete_audio", "enrich_audio",
    "create_video_upload", "upload_video_part", "complete_video_upload", "abort_video_upload",
    "start_export", "get_export_job", "download_export",
    "list_custom_domains", "create_custom_domain", "refresh_custom_domain", "delete_custom_domain",
    "list_presets", "upsert_preset", "delete_preset",
    "list_projects", "create_project", "update_project", "delete_project",
}
# Not wrapped on purpose: dashboard-session endpoints, the public playground,
# health, and surfaces the SDK does not cover yet.
IGNORED = {
    "claim_upload", "dashboard_upload", "dashboard_delete_image", "playground_upload", "playground_generate",
    # The web dashboard's session-JWT endpoints (an API key is rejected): list/search, AI descriptions, AI tags.
    "dashboard_list_images", "dashboard_describe_image", "dashboard_list_tags", "dashboard_update_upload",
    "health_check", "serve_image",
    # Billing: a person pays or cancels, so it is a dashboard/portal flow, not an SDK call.
    "start_checkout", "open_billing_portal",
    "list_collections", "get_collection", "close_collection",
    # Advanced image, webhook, share-link, and anonymous-playground surfaces are intentionally separate.
    "describe_image", "edit_image", "list_image_tags", "playground_video_upload", "playground_audio_upload",
    "list_webhooks", "create_webhook", "update_webhook", "delete_webhook",
    "rotate_webhook_secret", "list_webhook_deliveries",
    "create_share_link", "list_share_links", "revoke_share_link", "get_share_link", "unlock_share_link",
}

req = urllib.request.Request(
    "https://api.pixelvault.dev/openapi.json",
    headers={"User-Agent": "pixelvault-sdk-python-ci"},
)
with urllib.request.urlopen(req) as res:
    spec = json.load(res)

live = {
    op["operationId"]
    for item in spec["paths"].values()
    for op in item.values()
    if isinstance(op, dict) and "operationId" in op
}
new = sorted(live - COVERED - IGNORED)
gone = sorted(COVERED - live)
if new or gone:
    print(f"New operations to cover or ignore: {new}")
    print(f"Covered operations no longer in the API: {gone}")
    sys.exit(1)
print(f"spec coverage ok: {len(COVERED)} covered, {len(IGNORED)} ignored")
