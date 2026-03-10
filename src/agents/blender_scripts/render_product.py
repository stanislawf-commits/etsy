"""
render_product.py — Blender 4.x headless script do renderowania STL.

Wywołanie przez blender_render_agent.py:
  blender --background --python render_product.py -- \
    --stl /path/to/model.stl \
    --out /path/to/output.jpg \
    --mode hero|lifestyle|detail|sizes \
    --title "Product Name" \
    --size_label "M · 75mm"

Wymaga Blender 4.0+ z bpy.
"""
import sys
import math
import os

# Parsuj argumenty po '--'
argv = sys.argv
if "--" in argv:
    argv = argv[argv.index("--") + 1:]
else:
    argv = []

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--stl",        required=True)
parser.add_argument("--out",        required=True)
parser.add_argument("--mode",       default="hero",
                    choices=["hero", "lifestyle", "detail", "sizes_item"])
parser.add_argument("--title",      default="Cookie Cutter")
parser.add_argument("--size_label", default="M · 75mm")
parser.add_argument("--res",        type=int, default=2000)
args = parser.parse_args(argv)

import bpy

# ── Reset sceny ───────────────────────────────────────────────────────────────

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
for block in list(bpy.data.meshes):
    bpy.data.meshes.remove(block)

# ── Import STL ────────────────────────────────────────────────────────────────

stl_path_abs = os.path.abspath(args.stl)
print(f"Importing STL: {stl_path_abs}")

# Blender 4.0 — próbuj nowe API, fallback na stare
imported = False
try:
    bpy.ops.wm.stl_import(filepath=stl_path_abs)
    if bpy.context.selected_objects:
        imported = True
except Exception as e:
    print(f"wm.stl_import failed: {e}")

if not imported:
    try:
        bpy.ops.import_mesh.stl(filepath=stl_path_abs)
        if bpy.context.selected_objects:
            imported = True
    except Exception as e:
        print(f"import_mesh.stl failed: {e}")

if not imported or not bpy.context.selected_objects:
    print(f"ERROR: Could not import STL: {stl_path_abs}")
    sys.exit(1)

obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj

# Wycentruj i normalizuj skalę
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
obj.location = (0, 0, 0)

# Ustaw orientację — Z-up
obj.rotation_euler = (0, 0, 0)

# Skaluj żeby pasował do ~2 jednostek (blender units)
dims = obj.dimensions
max_dim = max(dims.x, dims.y, dims.z)
if max_dim > 0:
    scale_factor = 2.0 / max_dim
    obj.scale = (scale_factor, scale_factor, scale_factor)

# Zrób mesh single-user przed transform_apply
obj.data = obj.data.copy()
bpy.ops.object.transform_apply(scale=True)

# Przesuń na podłogę (Z=0 = dół obiektu)
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
obj.location.z = obj.dimensions.z / 2

# ── Materiał PLA ──────────────────────────────────────────────────────────────

mat = bpy.data.materials.new(name="PLA_White")
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links

nodes.clear()

# Principled BSDF — matowy biały PLA
bsdf = nodes.new("ShaderNodeBsdfPrincipled")
bsdf.location = (0, 0)

if args.mode == "lifestyle":
    # Ciepły kremowy kolor dla lifestyle
    bsdf.inputs["Base Color"].default_value = (0.98, 0.96, 0.90, 1.0)
else:
    # Czysta biel dla hero/detail
    bsdf.inputs["Base Color"].default_value = (0.97, 0.97, 0.97, 1.0)

bsdf.inputs["Roughness"].default_value        = 0.55
bsdf.inputs["Specular IOR Level"].default_value = 0.25
bsdf.inputs["Sheen Weight"].default_value     = 0.05

out = nodes.new("ShaderNodeOutputMaterial")
out.location = (300, 0)
links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

obj.data.materials.append(mat)

# ── Podłoga (plane) ───────────────────────────────────────────────────────────

bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = "Floor"

floor_mat = bpy.data.materials.new(name="Floor_Mat")
floor_mat.use_nodes = True
fn = floor_mat.node_tree.nodes
fl = floor_mat.node_tree.links
fn.clear()

floor_bsdf = fn.new("ShaderNodeBsdfPrincipled")
floor_out   = fn.new("ShaderNodeOutputMaterial")
floor_out.location = (300, 0)

if args.mode == "lifestyle":
    floor_bsdf.inputs["Base Color"].default_value = (0.96, 0.90, 0.78, 1.0)  # kremowe drewno
    floor_bsdf.inputs["Roughness"].default_value = 0.70
else:
    floor_bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    floor_bsdf.inputs["Roughness"].default_value = 0.90

fl.new(floor_bsdf.outputs["BSDF"], floor_out.inputs["Surface"])
floor.data.materials.append(floor_mat)

# ── Oświetlenie ───────────────────────────────────────────────────────────────

def add_area_light(name, location, energy, color=(1,1,1), size=3.0):
    bpy.ops.object.light_add(type='AREA', location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.color  = color
    light.data.size   = size
    # Skieruj na środek sceny
    direction = (-location[0], -location[1], -location[2])
    import mathutils
    light.rotation_euler = mathutils.Vector(direction).to_track_quat('-Z', 'Y').to_euler()
    return light

# Key light — główne oświetlenie
add_area_light("Key",  location=(3, -3, 5), energy=300, color=(1.0, 0.98, 0.95))
# Fill light — wypełnienie cieni
add_area_light("Fill", location=(-4, -1, 3), energy=80,  color=(0.9, 0.95, 1.0))
# Rim light — podświetlenie krawędzi
add_area_light("Rim",  location=(0,  5, 2), energy=120, color=(1.0, 1.0, 1.0))

# ── Kamera ────────────────────────────────────────────────────────────────────

bpy.ops.object.camera_add()
cam = bpy.context.active_object
cam.name = "Camera"
bpy.context.scene.camera = cam

if args.mode == "detail":
    # Widok z góry — zbliżenie na szczegóły
    cam.location = (0, 0, 5)
    cam.rotation_euler = (0, 0, 0)
    cam.data.lens = 85
elif args.mode in ("hero", "sizes_item"):
    # 3/4 angle — standardowy widok produktu
    cam.location = (2.8, -2.8, 3.5)
    import mathutils
    direction = mathutils.Vector((0, 0, 0.5)) - mathutils.Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = 70
elif args.mode == "lifestyle":
    # Lekko wyżej z boku — kontekstowy widok
    cam.location = (3.2, -2.4, 4.0)
    import mathutils
    direction = mathutils.Vector((0, 0, 0.4)) - mathutils.Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = 60

# ── Świat — tło ───────────────────────────────────────────────────────────────

world = bpy.data.worlds["World"]
world.use_nodes = True
wn = world.node_tree.nodes
wl = world.node_tree.links
wn.clear()

bg_node  = wn.new("ShaderNodeBackground")
out_node = wn.new("ShaderNodeOutputWorld")
out_node.location = (300, 0)

if args.mode == "lifestyle":
    bg_node.inputs["Color"].default_value    = (0.95, 0.90, 0.80, 1.0)
    bg_node.inputs["Strength"].default_value = 0.8
else:
    bg_node.inputs["Color"].default_value    = (1.0, 1.0, 1.0, 1.0)
    bg_node.inputs["Strength"].default_value = 1.2

wl.new(bg_node.outputs["Background"], out_node.inputs["Surface"])

# ── Ustawienia renderu ────────────────────────────────────────────────────────

scene = bpy.context.scene
scene.render.engine         = 'BLENDER_EEVEE_NEXT' if hasattr(bpy.types, 'EEVEE_NEXT_RenderSettings') else 'BLENDER_EEVEE'
scene.render.resolution_x   = args.res
scene.render.resolution_y   = args.res
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'JPEG'
scene.render.image_settings.quality     = 92
scene.render.filepath       = args.out

# EEVEE ustawienia
if hasattr(scene, 'eevee'):
    scene.eevee.use_ssr         = True   # screen-space reflections
    scene.eevee.use_bloom       = False
    scene.eevee.shadow_cube_size = '512'
    scene.eevee.taa_render_samples = 64

# ── Render ────────────────────────────────────────────────────────────────────

bpy.ops.render.render(write_still=True)
print(f"Rendered: {args.out}")
