# Asset Generator

Generate PNG images (Gemini) and GLB 3D models (Tripo3D + Meshy) from text prompts.

## CLI Reference

Tools live at `${CLAUDE_SKILL_DIR}/tools/`. Run from the project root.

### Generate image (5-10 cents)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py image \
  --prompt "the full prompt" -o assets/img/car.png
```

`--size` (default `1K`): `512` (5c), `1K` (7c), `2K` (10c)
`--aspect-ratio` (default `1:1`): `1:1`, `1:4`, `1:8`, `2:3`, `3:2`, `3:4`, `4:1`, `4:3`, `4:5`, `5:4`, `8:1`, `9:16`, `16:9`, `21:9`

Typical combos: `--size 2K --aspect-ratio 16:9` (landscape bg), `--size 2K --aspect-ratio 9:16` (portrait), `--size 1K` (textures, sprites, 3D refs).

### Remove background

Uses rembg mask + alpha matting. Handles semi-transparent objects, fine edges, hair, glass, particles. Auto-detects the background color from corner pixels. Dependencies in `${CLAUDE_SKILL_DIR}/tools/requirements.txt`.

If rembg is not installed:
```bash
pip install rembg[gpu,cli]   # use rembg[cpu,cli] if no GPU
rembg d isnet-anime          # download model
```

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/rembg_matting.py \
  assets/img/car.png -o assets/img/car_nobg.png
```

### Generate sprite sheet (7 cents)

Always 4x4 = exactly 16 cells. All 16 must be used — no more, no less. Template and grid instructions are injected automatically; you provide only the subject and BG color.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py spritesheet \
  --prompt "Animation: a knight swinging a sword" \
  --bg "#4A6741" -o assets/img/knight_swing_raw.png
```

- `--prompt` — subject only. Don't specify frame count (system prompt handles it). For animations describe the action; for collections number each item 1-16.
- `--bg` — background color hex (default: `#00FF00`). See BG color strategy below.

### Process sprite sheet

Crops red grid lines. Choose mode based on use case:

**Animation frames** → output single sheet for `Sprite2D` (`hframes=4, vframes=4`):
```bash
# Keep background (textures, solid-color game BG)
python3 ${CLAUDE_SKILL_DIR}/tools/spritesheet_slice.py keep-bg \
  assets/img/knight_raw.png -o assets/img/knight.png

# Remove background (sprites, characters — preferred)
python3 ${CLAUDE_SKILL_DIR}/tools/spritesheet_slice.py clean-bg \
  assets/img/knight_raw.png -o assets/img/knight.png
```

**Collection of distinct objects** (items, icons, props) → split into 16 individual PNGs:
```bash
# Split with background kept
python3 ${CLAUDE_SKILL_DIR}/tools/spritesheet_slice.py split-bg \
  assets/img/items_raw.png -o assets/img/items/

# Split with background removed (preferred for in-game objects)
python3 ${CLAUDE_SKILL_DIR}/tools/spritesheet_slice.py split-clean \
  assets/img/items_raw.png -o assets/img/items/ \
  --names "apple,banana,orange,grape,cherry,lemon,pear,plum,peach,melon,kiwi,mango,berry,fig,lime,coconut"
```

For split modes, `-o` is the output **directory**. `--names` provides filenames (without `.png`) for each cell left-to-right, top-to-bottom. Without `--names`, files are numbered `01.png`..`16.png`.

### Convert image to GLB (30-60 cents)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py glb \
  --image assets/img/car.png --quality medium -o assets/glb/car.glb
```

### Rig a model (20 cents)

Adds a skeleton to a generated 3D model. Requires the `task_id` from the `glb` command output.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py rig \
  --task-id TASK_ID_FROM_GLB --rig-type biped --spec mixamo \
  -o assets/glb/character_rigged.glb
```

- `--rig-type`: `biped` (default), `quadruped`, `hexapod`, `octopod`, `avian`, `serpentine`, `aquatic`, `others`
- `--spec`: `mixamo` (Mixamo-compatible, default) or `tripo` (Tripo native)
- `--format`: `glb` (default) or `fbx`

### Animate a rigged model (10 cents per animation)

Applies preset animations to a rigged model. Requires the `task_id` from the `rig` command output.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py animate \
  --task-id TASK_ID_FROM_RIG --animations idle,walk,run \
  -o assets/glb/character_animated.glb
```

Available animations: `idle`, `walk`, `run`, `dive`, `climb`, `jump`, `slash`, `shoot`, `hurt`, `fall`, `turn`, `quadruped_walk`, `hexapod_walk`, `octopod_walk`, `serpentine_march`, `aquatic_march`

- `--in-place`: no root motion (character stays at origin)
- `--no-bake`: don't bake animation to bones
- `--format`: `glb` (default) or `fbx`

### Stylize a model (20 cents)

Applies a visual stylization effect to a generated model.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py stylize \
  --task-id TASK_ID_FROM_GLB --style voxel \
  -o assets/glb/character_voxel.glb
```

Styles: `lego`, `voxel`, `voronoi`, `minecraft`

- `--block-size`: resolution (default: 80, higher = more detail)

### Meshy: Image to 3D (20 credits)

Alternative to Tripo3D. Supports text-to-3D directly, Meshy-6 model, and built-in remeshing. Requires `MESHY_API_KEY` env var.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py meshy_img2glb \
  --image assets/img/car.png -o assets/glb/car_meshy.glb
```

- `--ai-model`: `meshy-5`, `meshy-6`, or `latest` (default)
- `--polycount`: target face count, 100-300000 (default: 30000)
- `--no-pbr`: skip PBR map generation

Also accepts image URLs: `--image "https://example.com/car.png"`

### Meshy: Text to 3D (30 credits)

Generate a 3D model directly from a text prompt (no image needed). Two-phase: preview then refine.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py meshy_txt2glb \
  --prompt "A stylized medieval sword with ornate handle" \
  -o assets/glb/sword.glb
```

### Meshy: Rig (10 credits)

Auto-rig a humanoid model. Only works with textured humanoid GLBs under 300k faces.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py meshy_rig \
  --task-id MESHY_TASK_ID -o assets/glb/char_rigged.glb
```

- `--height`: character height in meters (default: 1.7)

### Meshy: Animate (5 credits)

Apply an animation from Meshy's library to a rigged model.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py meshy_animate \
  --rig-task-id RIG_TASK_ID --action-id 1 \
  -o assets/glb/char_walk.glb
```

- `--action-id`: animation ID from Meshy's animation library
- `--format`: `glb` (default) or `fbx`

### Meshy: Remesh (5 credits)

Retopologize or convert a model's mesh.

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py meshy_remesh \
  --task-id TASK_ID --polycount 5000 -o assets/glb/car_lowpoly.glb
```

- `--topology`: `triangle` (default) or `quad`

### Set budget

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py set_budget 500
```

Sets the generation budget to 500 cents. All subsequent generations check remaining budget and reject if insufficient. CRITICAL: only call once at the start, and only when the user explicitly provides a budget.

### Output format

JSON to stdout: `{"ok": true, "path": "assets/img/car.png", "cost_cents": 7}`

On failure: `{"ok": false, "error": "...", "cost_cents": 0}`

Progress goes to stderr.

## Cost Table

| Operation | Preset | Cost | Notes |
|-----------|--------|------|-------|
| Image | --size 512 | 5 cents | Configurable aspect ratio |
| Image | --size 1K | 7 cents | Default. Configurable aspect ratio |
| Image | --size 2K | 10 cents | HQ objects, textures, backgrounds |
| Image | --size 4K | 15 cents | Large game maps, panoramic backgrounds |
| Sprite sheet | — | 7 cents | 1K, 4x4 grid (16 cells, 256x256 each) |
| GLB | medium | 30 cents | 20k faces, good default |
| GLB | lowpoly | 40 cents | 5k faces, smart topology |
| GLB | high | 40 cents | Adaptive faces, detailed textures (+10c) |
| GLB | ultra | 60 cents | Detailed textures + geometry (+10c +20c) |
| Rig | — | 20 cents | Add skeleton to model |
| Animate | — | 10 cents/anim | Apply preset animation to rigged model |
| Stylize | — | 20 cents | Lego, voxel, voronoi, minecraft |
| **Meshy** | | | |
| Meshy img→3D | — | 20 cents | Image to GLB via Meshy |
| Meshy txt→3D | — | 30 cents | Text to GLB (preview + refine) |
| Meshy rig | — | 10 cents | Auto-rig humanoid model |
| Meshy animate | — | 5 cents | Apply animation from library |
| Meshy remesh | — | 5 cents | Retopologize / convert mesh |

A full 3D asset (image + GLB) costs 37 cents at medium quality (Tripo3D) or 27 cents (Meshy). A rigged + animated character costs ~67 cents (Tripo3D) or ~42 cents (Meshy). A texture is 7 cents. A sprite sheet is 7 cents for 16 frames/items.

## Image Resolution

Use the full generation resolution — don't downscale for aesthetic reasons.
- Default (`1K`): textures, sprites, 3D references
- `2K`: HQ objects/textures, backgrounds, title screens
- `4K`: large game maps (zoom into regions instead of multiple smaller images), panoramic backgrounds
- `512`: quick tests, low-cost assets
- Sprite sheets: 1024x1024 total → **256x256 per cell** (after grid crop ~248x248)

## What to Generate — Cheatsheet

**CRITICAL: Never prompt for "transparent background" — the generator draws a checkerboard. Always use a solid color background, then remove with `rembg_matting.py`.**

### Background / large scenic image (10c)

Title screens, sky panoramas, parallax layers, environmental art. Best place for art direction language.

```
{description in the art style}. {composition instructions}.
```
`image --prompt "..." --size 2K --aspect-ratio 16:9 -o path.png`

No post-processing — use as-is.

### Texture (7c)

Tileable surfaces: ground, walls, floors, UI panels.

```
{name}, {description}. Top-down view, uniform lighting, no shadows, seamless tileable texture, suitable for game engine tiling, clean edges.
```
`image --prompt "..." -o path.png`

No background removal — the entire image IS the texture.

### Single object / sprite (7c)

**With background** (object on a known scene background):
```
{name}, {description}.
```

**Transparent** (characters, props, icons, UI elements) — **CRITICAL: prompt must include a solid flat background color.** Without it, the generator draws a detailed/noisy background that rembg cannot cleanly separate:
```
{name}, {description}. Centered on a solid {bg_color} background.
```
Then: `rembg_matting.py input.png -o output.png`

### 3D model reference (7c) + GLB (30-60c)

```
3D model reference of {name}. {description}. 3/4 front elevated camera angle, solid white background, soft diffused studio lighting, matte material finish, single centered subject, no shadows on background. Any windows or glass should be solid tinted (opaque).
```
Then: `glb --image ... -o ...` — do NOT remove the background; Tripo3D needs the solid white bg for clean separation.

Key: 3/4 front elevated angle, solid white/gray bg, matte finish (no reflections), opaque glass, single centered subject.

### Animated 3D character (7c + 30c + 20c + 10c/anim = ~67c+)

Full pipeline: image → GLB → rig → animate. Each step outputs a `task_id` for chaining.

```bash
# 1. Generate reference image (7c)
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py image --prompt "3D model reference of a knight..." -o assets/img/knight.png

# 2. Convert to GLB (30c) — note the task_id in output
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py glb --image assets/img/knight.png -o assets/glb/knight.glb

# 3. Rig with skeleton (20c) — use task_id from step 2
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py rig --task-id TASK_ID -o assets/glb/knight_rigged.glb

# 4. Apply animations (10c each) — use task_id from step 3
python3 ${CLAUDE_SKILL_DIR}/tools/asset_gen.py animate --task-id RIG_TASK_ID --animations idle,walk,run,slash -o assets/glb/knight_animated.glb
```

For quadrupeds use `--rig-type quadruped` and animations like `quadruped_walk`.

### Animation → Spritesheet (7c)

16 cells in a 4x4 grid. Flexible layouts:
- 16 frames of one subject (walk cycle, attack, bounce)
- 4 objects x 4 frames each (4 enemies x 4 walk frames)
- 2 objects x 8 frames (split across rows)

The longer/more complex the animation, the more likely it breaks — keep motions simple.

```
Animation: a slime bouncing
```

Post-processing:
- **Transparent sprites** (preferred): `clean-bg` → single sheet for `Sprite2D` (`hframes=4, vframes=4`)
- **With background:** `keep-bg` → single sheet

### Asset kit (16 objects, consistent style) → Spritesheet (7c)

Generate 16 small objects that share the same visual style (items, icons, props, tiles). Cheaper and more consistent than 16 individual calls (7c vs 112c).

```
Items: 1: red apple 2: banana 3: orange 4: grape 5: cherry ...
```

Number every item 1-16. Don't specify grid layout — system prompt handles it.

Post-processing — split into individual images:
- **Transparent** (preferred): `split-clean -o dir/ --names "apple,banana,..."`
- **With background:** `split-bg -o dir/ --names "apple,banana,..."`

---

### BG color strategy (applies to all transparent assets)

Pick a `--bg` / prompt bg color that is (1) **distinct from the subject** so rembg separates cleanly, and (2) **close to the expected in-game environment** so residual fringe blends naturally.

Examples: forest game → `#4A6741`; sky/water → `#4A6B8A`; dungeon → `#2A2A2A`; generic → `#808080`.

Avoid pure chromakey colors like `#00FF00` — they create unnatural green fringing.

## Tips

- Generate multiple images in parallel via multiple Bash calls in one message.
- Always review generated PNGs before GLB conversion — read each image and check: centered? complete? clean background? Regenerate bad ones first; a bad image wastes 30+ cents on GLB.
- Convert approved images to GLBs in parallel.
