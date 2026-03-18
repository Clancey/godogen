"""Meshy AI API client — image-to-3D, text-to-3D, rigging, animation, remesh.

API docs: https://docs.meshy.ai/en
"""

import os
import time
from pathlib import Path

import requests

API_BASE = "https://api.meshy.ai/openapi"

# AI model versions
MESHY_5 = "meshy-5"
MESHY_6 = "meshy-6"
MESHY_LATEST = "latest"


def get_api_key() -> str:
    key = os.environ.get("MESHY_API_KEY")
    if not key:
        raise ValueError("MESHY_API_KEY environment variable not set")
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
    }


def _poll(endpoint: str, timeout: int = 600, interval: int = 5) -> dict:
    """Poll a Meshy task until completion."""
    headers = _headers()
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{API_BASE}{endpoint}", headers=headers)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        if status == "SUCCEEDED":
            return data
        elif status in ("FAILED", "CANCELED"):
            err = data.get("task_error", {}).get("message", status)
            raise RuntimeError(f"Meshy task failed: {err}")

        time.sleep(interval)

    raise TimeoutError(f"Meshy task timed out after {timeout}s")


def _download(url: str, output_path: Path) -> Path:
    resp = requests.get(url)
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    return output_path


# --- Image to 3D ---

def image_to_3d(
    image_url: str,
    output_path: Path,
    ai_model: str = MESHY_LATEST,
    target_polycount: int = 30000,
    topology: str = "triangle",
    enable_pbr: bool = True,
    should_remesh: bool = False,
    target_formats: list[str] | None = None,
    timeout: int = 600,
) -> str:
    """Convert an image to a 3D model. Returns task_id.

    Args:
        image_url: Public URL or base64 data URI of the image
        output_path: Where to save the GLB
        ai_model: "meshy-5", "meshy-6", or "latest"
        target_polycount: 100-300000 (default 30000)
        topology: "triangle" or "quad"
        enable_pbr: Generate PBR texture maps
        should_remesh: Run remesh pass
        target_formats: Output formats (default: ["glb"])
        timeout: Max seconds to wait
    """
    payload = {
        "image_url": image_url,
        "ai_model": ai_model,
        "target_polycount": target_polycount,
        "topology": topology,
        "enable_pbr": enable_pbr,
        "should_remesh": should_remesh,
        "should_texture": True,
    }
    if target_formats:
        payload["target_formats"] = target_formats

    resp = requests.post(f"{API_BASE}/v1/image-to-3d", headers=_headers(), json=payload)
    resp.raise_for_status()
    task_id = resp.json()["result"]
    print(f"  Meshy image-to-3d task: {task_id}")

    result = _poll(f"/v1/image-to-3d/{task_id}", timeout=timeout)
    print(f"  Meshy completed")

    glb_url = result.get("model_urls", {}).get("glb")
    if not glb_url:
        raise ValueError(f"No GLB URL in result: {result.get('model_urls', {}).keys()}")
    _download(glb_url, output_path)
    return task_id


# --- Text to 3D ---

def text_to_3d(
    prompt: str,
    output_path: Path,
    ai_model: str = MESHY_LATEST,
    target_polycount: int = 30000,
    topology: str = "triangle",
    enable_pbr: bool = True,
    timeout: int = 600,
) -> str:
    """Generate a 3D model from text. Two-phase: preview then refine. Returns refine task_id."""
    # Phase 1: Preview
    payload = {
        "mode": "preview",
        "prompt": prompt,
        "ai_model": ai_model,
        "target_polycount": target_polycount,
        "topology": topology,
    }
    resp = requests.post(f"{API_BASE}/v2/text-to-3d", headers=_headers(), json=payload)
    resp.raise_for_status()
    preview_id = resp.json()["result"]
    print(f"  Meshy text-to-3d preview: {preview_id}")

    _poll(f"/v2/text-to-3d/{preview_id}", timeout=timeout)
    print(f"  Meshy preview completed")

    # Phase 2: Refine
    refine_payload = {
        "mode": "refine",
        "preview_task_id": preview_id,
        "enable_pbr": enable_pbr,
    }
    resp = requests.post(f"{API_BASE}/v2/text-to-3d", headers=_headers(), json=refine_payload)
    resp.raise_for_status()
    refine_id = resp.json()["result"]
    print(f"  Meshy text-to-3d refine: {refine_id}")

    result = _poll(f"/v2/text-to-3d/{refine_id}", timeout=timeout)
    print(f"  Meshy refine completed")

    glb_url = result.get("model_urls", {}).get("glb")
    if not glb_url:
        raise ValueError(f"No GLB URL in result: {result.get('model_urls', {}).keys()}")
    _download(glb_url, output_path)
    return refine_id


# --- Rigging ---

def rig_model(
    output_path: Path,
    input_task_id: str | None = None,
    model_url: str | None = None,
    height_meters: float = 1.7,
    timeout: int = 300,
) -> str:
    """Rig a humanoid model. Supply either input_task_id or model_url. Returns rig task_id."""
    payload: dict = {}
    if input_task_id:
        payload["input_task_id"] = input_task_id
    elif model_url:
        payload["model_url"] = model_url
    else:
        raise ValueError("Provide either input_task_id or model_url")

    payload["height_meters"] = height_meters

    resp = requests.post(f"{API_BASE}/v1/rigging", headers=_headers(), json=payload)
    resp.raise_for_status()
    task_id = resp.json()["result"]
    print(f"  Meshy rigging task: {task_id}")

    result = _poll(f"/v1/rigging/{task_id}", timeout=timeout)
    print(f"  Meshy rigging completed")

    # Download rigged GLB
    rig_result = result.get("result", {})
    glb_url = rig_result.get("rigged_character_glb_url")
    if not glb_url:
        raise ValueError(f"No rigged GLB URL in result: {rig_result.keys()}")
    _download(glb_url, output_path)
    return task_id


# --- Animation ---

def animate_model(
    rig_task_id: str,
    action_id: int,
    output_path: Path,
    out_format: str = "glb",
    fps: int | None = None,
    timeout: int = 300,
) -> str:
    """Apply an animation to a rigged model. Returns animation task_id.

    Args:
        rig_task_id: Task ID from rig_model()
        action_id: Animation ID from Meshy's animation library
        output_path: Where to save the animated model
        out_format: "glb" or "fbx"
        fps: Target FPS (24, 25, 30, or 60). None = default 30.
        timeout: Max seconds to wait
    """
    payload: dict = {
        "rig_task_id": rig_task_id,
        "action_id": action_id,
    }
    if fps:
        payload["post_process"] = {
            "operation_type": "change_fps",
            "fps": fps,
        }

    resp = requests.post(f"{API_BASE}/v1/animations", headers=_headers(), json=payload)
    resp.raise_for_status()
    task_id = resp.json()["result"]
    print(f"  Meshy animation task: {task_id}")

    result = _poll(f"/v1/animations/{task_id}", timeout=timeout)
    print(f"  Meshy animation completed")

    # Download based on format preference
    if out_format == "fbx":
        url = result.get("animation_fbx_url")
    else:
        url = result.get("animation_glb_url")
    if not url:
        raise ValueError(f"No animation URL in result for format {out_format}")
    _download(url, output_path)
    return task_id


# --- Remesh ---

def remesh_model(
    output_path: Path,
    input_task_id: str | None = None,
    model_url: str | None = None,
    target_polycount: int = 30000,
    topology: str = "triangle",
    timeout: int = 300,
) -> str:
    """Remesh/convert a model. Supply either input_task_id or model_url. Returns task_id."""
    payload: dict = {}
    if input_task_id:
        payload["input_task_id"] = input_task_id
    elif model_url:
        payload["model_url"] = model_url
    else:
        raise ValueError("Provide either input_task_id or model_url")

    payload["target_polycount"] = target_polycount
    payload["topology"] = topology
    payload["target_formats"] = ["glb"]

    resp = requests.post(f"{API_BASE}/v1/remesh", headers=_headers(), json=payload)
    resp.raise_for_status()
    task_id = resp.json()["result"]
    print(f"  Meshy remesh task: {task_id}")

    result = _poll(f"/v1/remesh/{task_id}", timeout=timeout)
    print(f"  Meshy remesh completed")

    glb_url = result.get("model_urls", {}).get("glb")
    if not glb_url:
        raise ValueError(f"No GLB URL in remesh result")
    _download(glb_url, output_path)
    return task_id
