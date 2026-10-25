"""KayKit dioramas. Layout data is importable without Blender for validation."""
from pathlib import Path
import math

CAST_MODELS = {
    "knight_mage": ("Knight", "Mage"),
    "rogue_duo": ("Rogue", "Rogue_Hooded"),
    "barbarian_mage": ("Barbarian", "Mage"),
    "ranger_knight": ("Ranger", "Knight"),
}
# Every world has 10 large anchors, 20 accents, a common stage and the same cameras.
_ANCHORS = {
    "room": ("furniture", [
        ("shelf_B_large_decorated", 2.7), ("couch_pillows", 3.2), ("shelf_A_big", 2.7),
        ("cabinet_medium_decorated", 1.8), ("cabinet_small_decorated", 1.6),
        ("armchair_pillows", 1.5), ("armchair", 1.5),
        ("lamp_standing", 2.2), ("cactus_medium_A", 1.3), ("table_low", 1.9)]),
    "forest": ("forest", [
        ("Tree_1_A_Color1", 4.2), ("Tree_3_A_Color1", 4.6), ("Tree_2_A_Color1", 4.2),
        ("Tree_4_A_Color1", 3.5), ("Tree_1_B_Color1", 3.5),
        ("Rock_1_A_Color1", 1.5), ("Rock_2_A_Color1", 1.5),
        ("Bush_1_A_Color1", 1.4), ("Bush_2_A_Color1", 1.4), ("Rock_3_A_Color1", 1.5)]),
    "dungeon": ("dungeon", [
        ("wall_arched", 3.5), ("wall_doorway", 3.5), ("wall_shelves", 3.5),
        ("pillar_decorated", 3.0), ("column", 3.0),
        ("barrel_large_decorated", 1.3), ("chest_gold", 1.3),
        ("sword_shield_gold", 1.6), ("crates_stacked", 1.6), ("table_medium_decorated_A", 1.8)]),
    "space": ("space", [
        ("basemodule_A", 3.6), ("basemodule_B", 3.6), ("basemodule_garage", 3.6),
        ("drill_structure", 3.0), ("windturbine_tall", 3.0),
        ("cargo_A_stacked", 1.5), ("spacetruck", 1.8),
        ("solarpanel", 2.0), ("lander_A", 2.0), ("landingpad_small", 2.0)]),
    "city": ("city", [
        ("building_A_withoutBase", 4.0), ("building_C_withoutBase", 4.5), ("building_E_withoutBase", 4.0),
        ("streetlight", 3.0), ("trafficlight_A", 3.0),
        ("car_taxi", 1.8), ("bench", 1.6),
        ("dumpster", 1.4), ("car_sedan", 1.8), ("road_straight_crossing", 2.5)]),
}
_ACCENTS = {
    "room": [("cactus_small_A", .55), ("book_set", .45), ("pictureframe_standing_A", .5), ("lamp_table", .8)],
    "forest": [("Grass_1_A_Color1", .7), ("Bush_3_A_Color1", .8), ("Rock_1_D_Color1", .65), ("Grass_2_B_Color1", .7)],
    "dungeon": [("barrel_small", .7), ("bottle_A_green", .45), ("candle_triple", .55), ("box_small_decorated", .7)],
    "space": [("rock_A", .7), ("cargo_B", .8), ("lights", .8), ("containers_A", .75)],
    "city": [("bush", .8), ("firehydrant", .7), ("box_A", .65), ("trash_A", .7)],
}
_LARGE_POSITIONS = [(-3, 4.8), (0, 5.2), (3, 4.8), (-3.3, 2.8), (3.3, 2.8),
                    (-3.4, .3), (3.4, .3), (-2.2, 3.8), (2.2, 3.8), (0, 3.3)]
_SMALL_POSITIONS = [(-3.7, -1.1), (-2.7, -1), (2.7, -1), (3.7, -1.1), (-3.8, 1.5),
                    (3.8, 1.5), (-2.3, 2.2), (2.3, 2.2), (-3.7, 4), (3.7, 4),
                    (-1.8, 5.2), (1.8, 5.2), (-3.3, 5.9), (0, 6), (3.3, 5.9),
                    (-2.9, 3.7), (2.9, 3.7), (-1, 3.4), (1, 3.4), (0, 4.7)]
ENVIRONMENT_LAYOUTS = {}
for _world, (_pack, _models) in _ANCHORS.items():
    ENVIRONMENT_LAYOUTS[_world] = [
        (_pack, model, x, y, size, 0)
        for (model, size), (x, y) in zip(_models, _LARGE_POSITIONS)
    ] + [(_pack, _ACCENTS[_world][i % 4][0], x, y, _ACCENTS[_world][i % 4][1], i * 37)
         for i, (x, y) in enumerate(_SMALL_POSITIONS)]


def asset_path(directory, pack, model):
    """Resolve both normal glTF and the author's older .gltf.glb file names."""
    root = Path(directory) / pack
    for suffix in (".glb", ".gltf", ".gltf.glb"):
        matches = sorted(root.rglob(model + suffix))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"KayKit asset missing: {pack}/{model}")


def build_scene(job, classic_characters=None):
    """Build imported textured geometry and return legacy robot/girl role slots."""
    import bpy
    from mathutils import Vector

    directory = job["assets_dir"]
    environment = job.get("environment", "room")
    cast = job.get("cast", "knight_mage")

    def bounds(objects):
        points = [o.matrix_world @ Vector(c) for o in objects if o.type == "MESH" for c in o.bound_box]
        return [min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]

    def model(pack, name, x, y, size, rotation=0, character=False):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(asset_path(directory, pack, name)))
        objects = set(bpy.data.objects) - before
        root = bpy.data.objects.new("KayKit_" + name, None)
        bpy.context.collection.objects.link(root)
        for obj in objects:
            if obj.parent not in objects:
                obj.parent = root
        bpy.context.view_layer.update()
        low, high = bounds(objects)
        span = high[2] - low[2] if character else max(b - a for a, b in zip(low, high))
        scale = size / max(span, .001)
        root.scale = (scale,) * 3
        root.location = (x - (low[0] + high[0]) * scale / 2,
                         y - (low[1] + high[1]) * scale / 2, -low[2] * scale)
        root.rotation_euler.z = math.radians(rotation)
        return root, objects

    if environment != "studio":
        keep = set()
        if cast == "classic" and classic_characters:
            for parts in classic_characters.values():
                keep.add(parts["root"])
                keep.update(parts["root"].children_recursive)
        for obj in list(bpy.data.objects):
            if obj not in keep:
                bpy.data.objects.remove(obj, do_unlink=True)
        colors = {"room": (.38, .29, .23), "forest": (.25, .43, .22),
                  "dungeon": (.3, .31, .36), "space": (.36, .33, .4), "city": (.35, .4, .44)}
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 2.4, -.22))
        floor = bpy.context.object
        floor.name = "KayKit_diorama_base"
        floor.scale = (9.5, 9, .4)
        mat = bpy.data.materials.new("Diorama base")
        mat.diffuse_color = (*colors[environment], 1)
        floor.data.materials.append(mat)
        bevel = floor.modifiers.new("Soft edges", "BEVEL")
        bevel.width, bevel.segments = .12, 3
        if environment == "room":
            wall = bpy.data.materials.new("Warm room walls")
            wall.diffuse_color = (.68, .63, .53, 1)
            for loc, scale in [((0, 6.8, 1.9), (9.5, .15, 4.2)),
                               ((-4.7, 2.4, 1.9), (.15, 9, 4.2))]:
                bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
                bpy.context.object.scale = scale
                bpy.context.object.data.materials.append(wall)
        for pack, name, x, y, size, rotation in ENVIRONMENT_LAYOUTS[environment]:
            model(pack, name, x, y, size, rotation)
    else:
        for obj in list(bpy.data.objects):
            if obj.name.startswith(("robot", "girl")):
                bpy.data.objects.remove(obj, do_unlink=True)

    if cast == "classic":
        return classic_characters

    # Imported bodies and the author's animation clips share Rig_Medium bone names.
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(asset_path(directory, "animations", "Rig_Medium_General")))
    idle = bpy.data.actions.get("Idle_A")
    talk = bpy.data.actions.get("Interact")
    for action in (idle, talk):
        if action:
            action.use_fake_user = True
    for obj in set(bpy.data.objects) - before:
        bpy.data.objects.remove(obj, do_unlink=True)

    result = {}
    for role, name, x in zip(("robot", "girl"), CAST_MODELS[cast], (-.95, .95)):
        root, objects = model("adventurers", name, x, 0, 2.2, character=True)
        tracks = []
        for arm in (o for o in objects if o.type == "ARMATURE"):
            arm.animation_data_clear()
            data = arm.animation_data_create()
            for action in (idle, talk):
                if not action:
                    continue
                track = data.nla_tracks.new()
                strip = track.strips.new(action.name, 0, action)
                if hasattr(action, "slots") and action.slots:
                    strip.action_slot = action.slots[0]
                strip.repeat = 1000
                track.mute = action == talk
                tracks.append(track)
        result[role] = {"root": root, "mouth": None, "head": Vector((x, 0, 1.8)), "tracks": tracks}

    # Workbench reads each mesh's active image texture for KayKit's gradient atlases.
    for mat in bpy.data.materials:
        if mat.use_nodes:
            images = [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"]
            if images:
                mat.node_tree.nodes.active = images[0]
    return result
