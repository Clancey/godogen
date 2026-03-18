#!/usr/bin/env python3
"""Asset Generator CLI - images (Gemini), 3D models (Tripo3D + Meshy).

Subcommands:
  image          Generate a PNG from a prompt (5-15 cents)
  spritesheet    Generate a 4x4 sprite sheet with template (7 cents)
  glb            Convert a PNG to a GLB 3D model via Tripo3D (30-60 cents)
  rig            Rig a Tripo3D model with a skeleton (20 cents)
  animate        Apply preset animation to a Tripo3D rigged model (10 cents)
  stylize        Apply stylization to a Tripo3D model (20 cents)
  meshy_img2glb  Image to 3D via Meshy (20 credits)
  meshy_txt2glb  Text to 3D via Meshy (30 credits)
  meshy_rig      Rig a Meshy model (humanoid only)
  meshy_animate  Apply animation to a Meshy rigged model
  meshy_remesh   Remesh/convert a Meshy model

Output: JSON to stdout. Progress to stderr.
"""

import argparse
import json
import sys
from pathlib import Path

from google import genai
from google.genai import types

from tripo3d import (
    MODEL_V3,
    image_to_glb,
    rig_model,
    retarget_animation,
    stylize_model,
    ANIMATIONS,
    STYLES,
    RIG_BIPED,
    SPEC_MIXAMO,
)
import meshy

TOOLS_DIR = Path(__file__).parent
TEMPLATE_SCRIPT = TOOLS_DIR / "spritesheet_template.py"
BUDGET_FILE = Path("assets/budget.json")


def _load_budget():
    if not BUDGET_FILE.exists():
        return None
    return json.loads(BUDGET_FILE.read_text())


def _spent_total(budget):
    return sum(v for entry in budget.get("log", []) for v in entry.values())


def check_budget(cost_cents: int):
    """Check remaining budget. Exit with error JSON if insufficient."""
    budget = _load_budget()
    if budget is None:
        return
    spent = _spent_total(budget)
    remaining = budget.get("budget_cents", 0) - spent
    if cost_cents > remaining:
        result_json(False, error=f"Budget exceeded: need {cost_cents}¢ but only {remaining}¢ remaining ({spent}¢ of {budget['budget_cents']}¢ spent)")
        sys.exit(1)


def record_spend(cost_cents: int, service: str):
    """Append a generation record to the budget log."""
    budget = _load_budget()
    if budget is None:
        return
    budget.setdefault("log", []).append({service: cost_cents})
    BUDGET_FILE.write_text(json.dumps(budget, indent=2) + "\n")

SPRITESHEET_SYSTEM_TPL = """\
Using the attached template image as an exact layout guide: generate a sprite sheet.
The image is a 4x4 grid of 16 equal cells separated by red lines.
Replace each numbered cell with the corresponding content, reading left-to-right, top-to-bottom (cell 1 = first, cell 16 = last).

Rules:
- KEEP the red grid lines exactly where they are in the template — do not remove, shift, or paint over them
- Each cell's content must be CENTERED in its cell and must NOT cross into adjacent cells
- CRITICAL: fill ALL empty space in every cell with flat solid {bg_color} — no gradients, no scenery, no patterns, just the plain color
- Maintain consistent style, lighting direction, and proportions across all 16 cells
- CRITICAL: do NOT draw the numbered circles from the template onto the output — replace them entirely with the actual drawing content"""

QUALITY_PRESETS = {
    "lowpoly": {
        "face_limit": 5000,
        "smart_low_poly": True,
        "texture_quality": "standard",
        "geometry_quality": "standard",
        "cost_cents": 40,
    },
    "medium": {
        "face_limit": 20000,
        "smart_low_poly": False,
        "texture_quality": "standard",
        "geometry_quality": "standard",
        "cost_cents": 30,
    },
    "high": {
        "face_limit": None,
        "smart_low_poly": False,
        "texture_quality": "detailed",
        "geometry_quality": "standard",
        "cost_cents": 40,
    },
    "ultra": {
        "face_limit": None,
        "smart_low_poly": False,
        "texture_quality": "detailed",
        "geometry_quality": "detailed",
        "cost_cents": 60,
    },
}


def result_json(ok: bool, path: str | None = None, cost_cents: int = 0, error: str | None = None, task_id: str | None = None):
    d = {"ok": ok, "cost_cents": cost_cents}
    if path:
        d["path"] = path
    if task_id:
        d["task_id"] = task_id
    if error:
        d["error"] = error
    print(json.dumps(d))


IMAGE_MODEL = "gemini-3.1-flash-image-preview"
IMAGE_SIZES = ["512", "1K", "2K", "4K"]
IMAGE_COSTS = {"512": 5, "1K": 7, "2K": 10, "4K": 15}
IMAGE_ASPECT_RATIOS = ["1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"]


def cmd_image(args):
    size = args.size
    cost = IMAGE_COSTS[size]
    check_budget(cost)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(
            image_size=size,
            aspect_ratio=args.aspect_ratio,
        ),
    )
    label = f"{size} {args.aspect_ratio}"

    print(f"Generating image ({label})...", file=sys.stderr)

    client = genai.Client()
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[args.prompt],
        config=config,
    )

    if response.parts is None:
        reason = "unknown"
        if response.candidates and response.candidates[0].finish_reason:
            reason = response.candidates[0].finish_reason
        result_json(False, error=f"Generation blocked (reason: {reason})")
        sys.exit(1)

    for part in response.parts:
        if part.inline_data is not None:
            output.write_bytes(part.inline_data.data)
            print(f"Saved: {output}", file=sys.stderr)
            record_spend(cost, "gemini")
            result_json(True, path=str(output), cost_cents=cost)
            return

    result_json(False, error="No image returned")
    sys.exit(1)


def generate_template(bg_color: str) -> bytes:
    """Generate a template PNG on the fly with the given BG color. Returns PNG bytes."""
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    subprocess.run(
        [sys.executable, str(TEMPLATE_SCRIPT), "-o", tmp, "--bg", bg_color],
        check=True, capture_output=True,
    )
    data = Path(tmp).read_bytes()
    Path(tmp).unlink()
    return data


def cmd_spritesheet(args):
    cost = IMAGE_COSTS["1K"]  # 7 cents
    check_budget(cost)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    bg = args.bg
    template_bytes = generate_template(bg)
    system = SPRITESHEET_SYSTEM_TPL.format(bg_color=bg)
    print(f"Generating sprite sheet (bg={bg})...", file=sys.stderr)

    client = genai.Client()
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[
            types.Part.from_bytes(data=template_bytes, mime_type="image/png"),
            args.prompt,
        ],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            system_instruction=system,
            image_config=types.ImageConfig(
                image_size="1K",
                aspect_ratio="1:1",
            ),
        ),
    )

    if response.parts is None:
        reason = "unknown"
        if response.candidates and response.candidates[0].finish_reason:
            reason = response.candidates[0].finish_reason
        result_json(False, error=f"Generation blocked (reason: {reason})")
        sys.exit(1)

    for part in response.parts:
        if part.inline_data is not None:
            output.write_bytes(part.inline_data.data)
            print(f"Saved: {output}", file=sys.stderr)
            record_spend(cost, "gemini")
            result_json(True, path=str(output), cost_cents=cost)
            return

    result_json(False, error="No image returned")
    sys.exit(1)


def cmd_glb(args):
    image_path = Path(args.image)
    if not image_path.exists():
        result_json(False, error=f"Image not found: {image_path}")
        sys.exit(1)

    preset = QUALITY_PRESETS.get(args.quality, QUALITY_PRESETS["medium"])
    check_budget(preset["cost_cents"])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Converting to GLB (quality={args.quality})...", file=sys.stderr)

    try:
        task_id = image_to_glb(
            image_path,
            output,
            model_version=MODEL_V3,
            face_limit=preset["face_limit"],
            smart_low_poly=preset["smart_low_poly"],
            texture_quality=preset["texture_quality"],
            geometry_quality=preset["geometry_quality"],
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(preset["cost_cents"], "tripo3d")
    result_json(True, path=str(output), cost_cents=preset["cost_cents"], task_id=task_id)


def cmd_rig(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 20
    check_budget(cost)

    print(f"Rigging model (task={args.task_id}, type={args.rig_type}, spec={args.spec})...", file=sys.stderr)

    try:
        rig_task_id = rig_model(
            args.task_id,
            output,
            rig_type=args.rig_type,
            spec=args.spec,
            out_format=args.format,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "tripo3d")
    result_json(True, path=str(output), cost_cents=cost, task_id=rig_task_id)


def cmd_animate(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    animations = args.animations.split(",")
    cost = 10 * len(animations)
    check_budget(cost)

    print(f"Animating model (task={args.task_id}, anims={animations})...", file=sys.stderr)

    try:
        anim_task_id = retarget_animation(
            args.task_id,
            output,
            animations=animations,
            out_format=args.format,
            bake_animation=not args.no_bake,
            animate_in_place=args.in_place,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "tripo3d")
    result_json(True, path=str(output), cost_cents=cost, task_id=anim_task_id)


def cmd_stylize(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 20
    check_budget(cost)

    print(f"Stylizing model (task={args.task_id}, style={args.style})...", file=sys.stderr)

    try:
        style_task_id = stylize_model(
            args.task_id,
            output,
            style=args.style,
            block_size=args.block_size,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "tripo3d")
    result_json(True, path=str(output), cost_cents=cost, task_id=style_task_id)


def cmd_meshy_img2glb(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 20
    check_budget(cost)

    # Convert local file to data URI if not a URL
    image_url = args.image
    if not image_url.startswith(("http://", "https://", "data:")):
        import base64
        image_path = Path(image_url)
        if not image_path.exists():
            result_json(False, error=f"Image not found: {image_url}")
            sys.exit(1)
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        image_url = f"data:image/png;base64,{b64}"

    print(f"Meshy image-to-3d (model={args.ai_model}, polys={args.polycount})...", file=sys.stderr)

    try:
        task_id = meshy.image_to_3d(
            image_url,
            output,
            ai_model=args.ai_model,
            target_polycount=args.polycount,
            enable_pbr=args.pbr,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "meshy")
    result_json(True, path=str(output), cost_cents=cost, task_id=task_id)


def cmd_meshy_txt2glb(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 30
    check_budget(cost)

    print(f"Meshy text-to-3d (model={args.ai_model})...", file=sys.stderr)

    try:
        task_id = meshy.text_to_3d(
            args.prompt,
            output,
            ai_model=args.ai_model,
            target_polycount=args.polycount,
            enable_pbr=args.pbr,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "meshy")
    result_json(True, path=str(output), cost_cents=cost, task_id=task_id)


def cmd_meshy_rig(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 10
    check_budget(cost)

    print(f"Meshy rigging (task={args.task_id})...", file=sys.stderr)

    try:
        task_id = meshy.rig_model(
            output,
            input_task_id=args.task_id,
            height_meters=args.height,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "meshy")
    result_json(True, path=str(output), cost_cents=cost, task_id=task_id)


def cmd_meshy_animate(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 5
    check_budget(cost)

    print(f"Meshy animate (rig={args.rig_task_id}, action={args.action_id})...", file=sys.stderr)

    try:
        task_id = meshy.animate_model(
            args.rig_task_id,
            args.action_id,
            output,
            out_format=args.format,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "meshy")
    result_json(True, path=str(output), cost_cents=cost, task_id=task_id)


def cmd_meshy_remesh(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cost = 5
    check_budget(cost)

    print(f"Meshy remesh (task={args.task_id}, polys={args.polycount})...", file=sys.stderr)

    try:
        task_id = meshy.remesh_model(
            output,
            input_task_id=args.task_id,
            target_polycount=args.polycount,
            topology=args.topology,
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(cost, "meshy")
    result_json(True, path=str(output), cost_cents=cost, task_id=task_id)


def cmd_set_budget(args):
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    budget = {"budget_cents": args.cents, "log": []}
    if BUDGET_FILE.exists():
        old = json.loads(BUDGET_FILE.read_text())
        budget["log"] = old.get("log", [])
    BUDGET_FILE.write_text(json.dumps(budget, indent=2) + "\n")
    spent = _spent_total(budget)
    print(json.dumps({"ok": True, "budget_cents": args.cents, "spent_cents": spent, "remaining_cents": args.cents - spent}))


def main():
    parser = argparse.ArgumentParser(description="Asset Generator — images (Gemini), 3D models (Tripo3D + Meshy)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_img = sub.add_parser("image", help="Generate a PNG image (5-15¢ depending on size)")
    p_img.add_argument("--prompt", required=True, help="Full image generation prompt")
    p_img.add_argument("--size", choices=IMAGE_SIZES, default="1K",
                       help="Resolution: 512 (5¢), 1K (7¢), 2K (10¢), 4K (15¢). Default: 1K.")
    p_img.add_argument("--aspect-ratio", choices=IMAGE_ASPECT_RATIOS, default="1:1",
                       help="Aspect ratio. Default: 1:1")
    p_img.add_argument("-o", "--output", required=True, help="Output PNG path")
    p_img.set_defaults(func=cmd_image)

    p_ss = sub.add_parser("spritesheet", help="Generate 4x4 sprite sheet (7 cents)")
    p_ss.add_argument("--prompt", required=True, help="What to generate (animation description or item list)")
    p_ss.add_argument("--bg", default="#00FF00", help="Background color hex (default: #00FF00 green). Choose a color absent from the subject.")
    p_ss.add_argument("-o", "--output", required=True, help="Output PNG path")
    p_ss.set_defaults(func=cmd_spritesheet)

    p_glb = sub.add_parser("glb", help="Convert PNG to GLB 3D model (30-40 cents)")
    p_glb.add_argument("--image", required=True, help="Input PNG path")
    p_glb.add_argument("--quality", default="medium", choices=list(QUALITY_PRESETS.keys()), help="Quality preset")
    p_glb.add_argument("-o", "--output", required=True, help="Output GLB path")
    p_glb.set_defaults(func=cmd_glb)

    p_rig = sub.add_parser("rig", help="Rig a model with a skeleton (20¢)")
    p_rig.add_argument("--task-id", required=True, help="Task ID of the model to rig")
    p_rig.add_argument("--rig-type", default="biped",
                       choices=["biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic", "others"],
                       help="Skeleton type (default: biped)")
    p_rig.add_argument("--spec", default="mixamo", choices=["mixamo", "tripo"],
                       help="Rig spec — mixamo for Mixamo-compatible, tripo for Tripo native (default: mixamo)")
    p_rig.add_argument("--format", default="glb", choices=["glb", "fbx"], help="Output format (default: glb)")
    p_rig.add_argument("-o", "--output", required=True, help="Output model path")
    p_rig.set_defaults(func=cmd_rig)

    p_anim = sub.add_parser("animate", help="Apply preset animation to a rigged model (10¢ per animation)")
    p_anim.add_argument("--task-id", required=True, help="Task ID of the rigged model")
    p_anim.add_argument("--animations", required=True,
                        help=f"Comma-separated animation names: {', '.join(ANIMATIONS)}")
    p_anim.add_argument("--format", default="glb", choices=["glb", "fbx"], help="Output format (default: glb)")
    p_anim.add_argument("--no-bake", action="store_true", help="Don't bake animation to bones")
    p_anim.add_argument("--in-place", action="store_true", help="Animate in place (no root motion)")
    p_anim.add_argument("-o", "--output", required=True, help="Output model path")
    p_anim.set_defaults(func=cmd_animate)

    p_style = sub.add_parser("stylize", help="Stylize a model (20¢)")
    p_style.add_argument("--task-id", required=True, help="Task ID of the model to stylize")
    p_style.add_argument("--style", required=True, choices=STYLES, help="Stylization effect")
    p_style.add_argument("--block-size", type=int, default=80, help="Block resolution (default: 80)")
    p_style.add_argument("-o", "--output", required=True, help="Output model path")
    p_style.set_defaults(func=cmd_stylize)

    # --- Meshy commands ---
    p_mi = sub.add_parser("meshy_img2glb", help="Image to 3D via Meshy (20 credits)")
    p_mi.add_argument("--image", required=True, help="Image path, URL, or data URI")
    p_mi.add_argument("--ai-model", default="latest", choices=["meshy-5", "meshy-6", "latest"],
                       help="Meshy AI model (default: latest)")
    p_mi.add_argument("--polycount", type=int, default=30000, help="Target polycount (default: 30000)")
    p_mi.add_argument("--pbr", action="store_true", default=True, help="Generate PBR maps (default: true)")
    p_mi.add_argument("--no-pbr", dest="pbr", action="store_false", help="Skip PBR maps")
    p_mi.add_argument("-o", "--output", required=True, help="Output GLB path")
    p_mi.set_defaults(func=cmd_meshy_img2glb)

    p_mt = sub.add_parser("meshy_txt2glb", help="Text to 3D via Meshy (30 credits)")
    p_mt.add_argument("--prompt", required=True, help="Text description (max 600 chars)")
    p_mt.add_argument("--ai-model", default="latest", choices=["meshy-5", "meshy-6", "latest"],
                       help="Meshy AI model (default: latest)")
    p_mt.add_argument("--polycount", type=int, default=30000, help="Target polycount (default: 30000)")
    p_mt.add_argument("--pbr", action="store_true", default=True, help="Generate PBR maps (default: true)")
    p_mt.add_argument("--no-pbr", dest="pbr", action="store_false", help="Skip PBR maps")
    p_mt.add_argument("-o", "--output", required=True, help="Output GLB path")
    p_mt.set_defaults(func=cmd_meshy_txt2glb)

    p_mr = sub.add_parser("meshy_rig", help="Rig a Meshy model (humanoid only)")
    p_mr.add_argument("--task-id", required=True, help="Meshy task ID of the model to rig")
    p_mr.add_argument("--height", type=float, default=1.7, help="Character height in meters (default: 1.7)")
    p_mr.add_argument("-o", "--output", required=True, help="Output rigged GLB path")
    p_mr.set_defaults(func=cmd_meshy_rig)

    p_ma = sub.add_parser("meshy_animate", help="Animate a Meshy rigged model")
    p_ma.add_argument("--rig-task-id", required=True, help="Meshy rig task ID")
    p_ma.add_argument("--action-id", type=int, required=True, help="Animation ID from Meshy library")
    p_ma.add_argument("--format", default="glb", choices=["glb", "fbx"], help="Output format (default: glb)")
    p_ma.add_argument("-o", "--output", required=True, help="Output animated model path")
    p_ma.set_defaults(func=cmd_meshy_animate)

    p_mrem = sub.add_parser("meshy_remesh", help="Remesh/convert a Meshy model")
    p_mrem.add_argument("--task-id", required=True, help="Meshy task ID of the model to remesh")
    p_mrem.add_argument("--polycount", type=int, default=30000, help="Target polycount (default: 30000)")
    p_mrem.add_argument("--topology", default="triangle", choices=["triangle", "quad"], help="Topology (default: triangle)")
    p_mrem.add_argument("-o", "--output", required=True, help="Output GLB path")
    p_mrem.set_defaults(func=cmd_meshy_remesh)

    p_budget = sub.add_parser("set_budget", help="Set the asset generation budget in cents")
    p_budget.add_argument("cents", type=int, help="Budget in cents")
    p_budget.set_defaults(func=cmd_set_budget)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
