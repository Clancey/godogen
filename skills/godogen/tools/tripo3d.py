"""Tripo3D API client — generation, rigging, animation, and stylization.

API docs: https://platform.tripo3d.ai/docs/generation

Model versions:
- Turbo-v1.0-20250506: Fast generation
- v3.0-20250812: Latest, supports geometry_quality=detailed (Ultra Mode)
- v2.5-20250123: Default in API

Rig model versions:
- v1.0-20240301: Original
- v2.0-20250506: Latest
"""

import os
import time
from pathlib import Path

import requests

API_BASE = "https://api.tripo3d.ai/v2/openapi"

# Model version constants
MODEL_TURBO = "Turbo-v1.0-20250506"
MODEL_V3 = "v3.0-20250812"
MODEL_V25 = "v2.5-20250123"

RIG_V1 = "v1.0-20240301"
RIG_V2 = "v2.0-20250506"

# Rig types (skeleton morphology)
RIG_BIPED = "biped"
RIG_QUADRUPED = "quadruped"
RIG_HEXAPOD = "hexapod"
RIG_OCTOPOD = "octopod"
RIG_AVIAN = "avian"
RIG_SERPENTINE = "serpentine"
RIG_AQUATIC = "aquatic"
RIG_OTHERS = "others"

# Rig spec (skeleton standard)
SPEC_MIXAMO = "mixamo"
SPEC_TRIPO = "tripo"

# Preset animations for retarget
ANIMATIONS = [
    "idle", "walk", "run", "dive", "climb", "jump",
    "slash", "shoot", "hurt", "fall", "turn",
    "quadruped_walk", "hexapod_walk", "octopod_walk",
    "serpentine_march", "aquatic_march",
]

# Stylization presets
STYLES = ["lego", "voxel", "voronoi", "minecraft"]


def get_api_key() -> str:
    key = os.environ.get("TRIPO3D_API_KEY")
    if not key:
        raise ValueError("TRIPO3D_API_KEY environment variable not set")
    return key


def create_task(
    image_path: Path,
    model_version: str = MODEL_V3,
    face_limit: int | None = None,
    smart_low_poly: bool = False,
    texture_quality: str = "standard",
    geometry_quality: str = "standard",
) -> str:
    """Create image-to-model task, returns task_id.

    Args:
        image_path: Path to input image
        model_version: API model version (MODEL_V3, MODEL_TURBO, etc)
        face_limit: Max faces (1000-20000 for smart_low_poly, adaptive if None)
        smart_low_poly: Hand-crafted low-poly topology (better for game assets)
        texture_quality: "standard" or "detailed"
        geometry_quality: "standard" or "detailed" (Ultra Mode, v3.0+ only)
    """
    api_key = get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    # Upload image first
    upload_url = f"{API_BASE}/upload"
    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, "image/png")}
        resp = requests.post(upload_url, headers=headers, files=files)
        resp.raise_for_status()
        upload_data = resp.json()

    image_token = upload_data["data"]["image_token"]

    # Create task
    task_url = f"{API_BASE}/task"
    payload = {
        "type": "image_to_model",
        "model_version": model_version,
        "file": {"type": "png", "file_token": image_token},
        "texture": True,
        "pbr": True,
    }

    if face_limit is not None:
        payload["face_limit"] = face_limit
    if smart_low_poly:
        payload["smart_low_poly"] = True
    if texture_quality != "standard":
        payload["texture_quality"] = texture_quality
    # geometry_quality only valid for v3.0+
    if geometry_quality != "standard" and "v3.0" in model_version:
        payload["geometry_quality"] = geometry_quality

    resp = requests.post(task_url, headers=headers, json=payload)
    resp.raise_for_status()
    task_data = resp.json()

    return task_data["data"]["task_id"]


def poll_task(task_id: str, timeout: int = 300, interval: int = 5) -> dict:
    """Poll task until completion, returns task result."""
    api_key = get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{API_BASE}/task/{task_id}"

    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()["data"]

        status = data["status"]
        if status == "success":
            return data
        elif status in ("failed", "cancelled", "unknown"):
            raise RuntimeError(f"Task {task_id} failed with status: {status}")

        time.sleep(interval)

    raise TimeoutError(f"Task {task_id} timed out after {timeout}s")


def _create_post_task(payload: dict, timeout: int = 300) -> tuple[str, dict]:
    """Create a post-processing task and poll to completion. Returns (task_id, result)."""
    api_key = get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.post(f"{API_BASE}/task", headers=headers, json=payload)
    resp.raise_for_status()
    task_id = resp.json()["data"]["task_id"]
    print(f"  Tripo3D task: {task_id} (type={payload['type']})")
    result = poll_task(task_id, timeout=timeout)
    print(f"  Tripo3D completed ({payload['type']})")
    return task_id, result


def download_model(task_result: dict, output_path: Path) -> Path:
    """Download model from task result. Checks pbr_model, model, base_model."""
    output = task_result.get("output", {})
    model_url = (
        output.get("pbr_model")
        or output.get("model")
        or output.get("base_model")
    )
    if not model_url:
        raise ValueError(f"No model URL in task output: {output.keys()}")
    resp = requests.get(model_url)
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    return output_path


def image_to_glb(
    image_path: Path,
    output_path: Path,
    model_version: str = MODEL_V3,
    face_limit: int | None = None,
    smart_low_poly: bool = False,
    texture_quality: str = "standard",
    geometry_quality: str = "standard",
    timeout: int = 300,
) -> Path:
    """Convert image to GLB model using Tripo3D API.

    Args:
        image_path: Path to input image (PNG)
        output_path: Path to save GLB file
        model_version: MODEL_V3, MODEL_TURBO, or MODEL_V25
        face_limit: Max faces (1000-20000 for smart_low_poly)
        smart_low_poly: Better topology for game assets
        texture_quality: "standard" or "detailed"
        geometry_quality: "standard" or "detailed" (Ultra Mode, v3.0+ only)
        timeout: Max seconds to wait for generation

    Returns:
        Path to downloaded GLB file
    """
    task_id = create_task(
        image_path,
        model_version=model_version,
        face_limit=face_limit,
        smart_low_poly=smart_low_poly,
        texture_quality=texture_quality,
        geometry_quality=geometry_quality,
    )
    print(f"  Tripo3D task: {task_id} (model={model_version}, geo={geometry_quality})")

    result = poll_task(task_id, timeout=timeout)
    print(f"  Tripo3D completed")

    download_model(result, output_path)
    return task_id


# --- Rigging ---

def check_riggable(task_id: str, timeout: int = 120) -> dict:
    """Check if a model can be rigged. Returns result with 'riggable' bool and suggested 'rig_type'."""
    _, result = _create_post_task({
        "type": "animate_prerigcheck",
        "original_model_task_id": task_id,
    }, timeout=timeout)
    return result


def rig_model(
    task_id: str,
    output_path: Path,
    rig_type: str = RIG_BIPED,
    spec: str = SPEC_MIXAMO,
    out_format: str = "glb",
    model_version: str = RIG_V2,
    timeout: int = 300,
) -> str:
    """Rig a generated model (add skeleton for animation). Returns rig task_id for chaining."""
    rig_task_id, result = _create_post_task({
        "type": "animate_rig",
        "original_model_task_id": task_id,
        "model_version": model_version,
        "out_format": out_format,
        "rig_type": rig_type,
        "spec": spec,
    }, timeout=timeout)
    download_model(result, output_path)
    return rig_task_id


# --- Animation retarget ---

def retarget_animation(
    task_id: str,
    output_path: Path,
    animations: list[str] | str = "idle",
    out_format: str = "glb",
    bake_animation: bool = True,
    export_with_geometry: bool = False,
    animate_in_place: bool = False,
    timeout: int = 300,
) -> str:
    """Apply preset animation(s) to a rigged model. Returns animation task_id."""
    if isinstance(animations, str):
        animations = [animations]

    anim_task_id, result = _create_post_task({
        "type": "animate_retarget",
        "original_model_task_id": task_id,
        "animations": animations,
        "out_format": out_format,
        "bake_animation": bake_animation,
        "export_with_geometry": export_with_geometry,
        "animate_in_place": animate_in_place,
    }, timeout=timeout)
    download_model(result, output_path)
    return anim_task_id


# --- Stylization ---

def stylize_model(
    task_id: str,
    output_path: Path,
    style: str = "voxel",
    block_size: int = 80,
    timeout: int = 300,
) -> str:
    """Apply a stylization effect to a model. Returns stylize task_id."""
    style_task_id, result = _create_post_task({
        "type": "stylize_model",
        "original_model_task_id": task_id,
        "style": style,
        "block_size": block_size,
    }, timeout=timeout)
    download_model(result, output_path)
    return style_task_id
