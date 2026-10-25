"""Runs inside Blender: build the studio, animate the lines, render PNG frames.

    blender -b --factory-startup -P blender_scene.py -- job.json

job.json: {"fps", "width", "height", "frames_dir",
           "frames": [1-based frame numbers to render],
           "lines": [{"who", "shot", "first", "last"}]}  # frame numbers
Prints "WIBE_FRAME <n>" after each written frame. Standalone on purpose:
Blender's Python does not see the wibecode package.
"""

import json
import math
import os
import sys

import bpy
from mathutils import Vector

job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
scene = bpy.context.scene


def material(name, rgb):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1)  # Workbench shades by this colour
    return mat


def add(kind, name, loc, size, mat, parent=None, **kwargs):
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(location=loc)
    elif kind == "ball":
        bpy.ops.mesh.primitive_ico_sphere_add(location=loc, subdivisions=2, **kwargs)
    elif kind == "tube":
        bpy.ops.mesh.primitive_cylinder_add(location=loc, vertices=10, **kwargs)
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(location=loc, vertices=10, **kwargs)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    obj.data.materials.append(mat)
    if parent is not None:
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()
    return obj


def empty(name, loc):
    bpy.ops.object.empty_add(location=loc)
    obj = bpy.context.object
    obj.name = name
    return obj


M = {
    "brick": material("brick", (0.55, 0.2, 0.12)),
    "wood": material("wood", (0.42, 0.24, 0.12)),
    "green": material("green", (0.25, 0.62, 0.3)),
    "dark": material("dark", (0.06, 0.06, 0.07)),
    "metal": material("metal", (0.35, 0.35, 0.38)),
    "screen": material("screen", (0.12, 0.14, 0.2)),
    "robot": material("robot", (0.9, 0.38, 0.25)),
    "skin": material("skin", (0.95, 0.6, 0.45)),
    "hair": material("hair", (0.92, 0.42, 0.22)),
    "beret": material("beret", (0.75, 0.1, 0.1)),
    "sweater": material("sweater", (0.22, 0.17, 0.3)),
    "jeans": material("jeans", (0.16, 0.2, 0.36)),
    "white": material("white", (0.95, 0.95, 0.95)),
}

# Studio: floor, brick wall, green screen, desk with a monitor, lamps, camera.
add("box", "floor", (0, 1, -0.05), (14, 12, 0.1), M["wood"])
add("box", "wall", (0, 3.2, 3), (14, 0.2, 6), M["brick"])
add("box", "greenscreen", (0.9, 3.05, 2.1), (3.6, 0.05, 4.2), M["green"])
add("box", "desk", (-2.4, 2.3, 0.75), (1.6, 0.8, 0.08), M["wood"])
add("box", "monitor", (-2.4, 2.4, 1.3), (1.1, 0.06, 0.7), M["dark"])
add("box", "monitor_screen", (-2.4, 2.36, 1.3), (1.0, 0.02, 0.6), M["screen"])
for x in (-1.6, 2.9):
    add("tube", "lamp_pole", (x, 2.4, 1.6), (0.06, 0.06, 3.2), M["metal"])
    add("cone", "lamp_head", (x, 2.3, 3.25), (0.5, 0.5, 0.5), M["dark"], rotation=(1.2, 0, 0))
add("box", "camera_body", (2.6, 0.6, 1.5), (0.45, 0.6, 0.35), M["dark"])
add("tube", "camera_lens", (2.6, 0.25, 1.5), (0.22, 0.22, 0.3), M["dark"], rotation=(1.5708, 0, 0))
add("tube", "tripod", (2.6, 0.6, 0.7), (0.06, 0.06, 1.4), M["metal"])

# Characters: one root empty each, so animation moves the whole body.
CHARACTERS = {}

robot = empty("robot", (-0.9, 0, 0))
add("box", "robot_body", (-0.9, 0, 1.15), (1.3, 1.0, 1.0), M["robot"], robot)
for i, dx in enumerate((-0.45, -0.15, 0.15, 0.45)):
    add("box", f"robot_leg{i}", (-0.9 + dx, 0, 0.33), (0.2, 0.2, 0.66), M["robot"], robot)
add("box", "robot_arm", (-0.15, -0.05, 1.05), (0.25, 0.3, 0.25), M["robot"], robot)
for dx in (-0.25, 0.25):
    add("box", "robot_eye", (-0.9 + dx, -0.51, 1.35), (0.09, 0.02, 0.2), M["dark"], robot)
robot_mouth = add("box", "robot_mouth", (-0.9, -0.51, 0.98), (0.18, 0.02, 0.05), M["dark"], robot)
CHARACTERS["robot"] = {"root": robot, "mouth": robot_mouth, "head": Vector((-0.9, 0, 1.25))}
CHARACTERS["robot"]["mouth_z"] = robot_mouth.scale.z

girl = empty("girl", (1.0, 0.2, 0))
add("tube", "girl_leg_l", (0.88, 0.2, 0.45), (0.18, 0.18, 0.9), M["jeans"], girl)
add("tube", "girl_leg_r", (1.12, 0.2, 0.45), (0.18, 0.18, 0.9), M["jeans"], girl)
add("tube", "girl_torso", (1.0, 0.2, 1.2), (0.6, 0.4, 0.7), M["sweater"], girl)
add("ball", "girl_hair_back", (1.0, 0.28, 1.83), (0.62, 0.55, 0.75), M["hair"], girl)
add("ball", "girl_head", (1.0, 0.18, 1.85), (0.5, 0.48, 0.55), M["skin"], girl)
add("tube", "girl_beret", (1.0, 0.2, 2.13), (0.62, 0.62, 0.1), M["beret"], girl, rotation=(0.15, 0.2, 0))
for dx in (-0.1, 0.1):
    add("ball", "girl_eye", (1.0 + dx, -0.06, 1.88), (0.06, 0.03, 0.08), M["dark"], girl)
girl_mouth = add("box", "girl_mouth", (1.0, -0.06, 1.72), (0.1, 0.02, 0.03), M["dark"], girl)
CHARACTERS["girl"] = {"root": girl, "mouth": girl_mouth, "head": Vector((1.0, 0.2, 1.85))}
CHARACTERS["girl"]["mouth_z"] = girl_mouth.scale.z

robot.rotation_euler.z = math.radians(12)
girl.rotation_euler.z = math.radians(-12)

bpy.ops.object.camera_add()
camera = bpy.context.object
scene.camera = camera

world = bpy.data.worlds.new("world")
world.color = (0.08, 0.06, 0.06)
scene.world = world

scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light = "STUDIO"
shading.color_type = "MATERIAL"
shading.show_shadows = True
shading.shadow_intensity = 0.35
shading.show_specular_highlight = False
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.3
scene.render.resolution_x = job["width"]
scene.render.resolution_y = job["height"]
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.fps = job["fps"]

SHOTS = {  # camera offset from the target and lens, per shot size
    "wide": (Vector((0.0, -5.2, 0.35)), 24),
    "medium": (Vector((0.0, -3.6, 0.2)), 32),
    "close": (Vector((0.0, -2.9, 0.05)), 40),
}


def point_camera(shot, who):
    if who is None:
        target = Vector((0.0, 0.3, 1.2))
    else:
        head = CHARACTERS[who]["head"]
        target = head if shot == "close" else Vector((head.x, head.y, head.z - 0.35))
    offset, lens = SHOTS[shot]
    camera.location = target + offset
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = lens


def pose(frame):
    t = frame / job["fps"]
    line = next((l for l in job["lines"] if l["first"] <= frame <= l["last"]), None)
    speaker = line["who"] if line else None
    for i, (name, parts) in enumerate(CHARACTERS.items()):
        talking = name == speaker
        bob = 0.025 * math.sin(2 * math.pi * 0.5 * t + i * 1.7)
        if talking:
            bob += 0.03 * abs(math.sin(2 * math.pi * 1.6 * t))
        parts["root"].location.z = bob
        opening = 3 * abs(math.sin(2 * math.pi * 3.5 * t)) if talking else 0
        parts["mouth"].scale.z = parts["mouth_z"] * (1 + opening)
    point_camera(line["shot"] if line else "wide", speaker)


frames_dir = job["frames_dir"]
for frame in job["frames"]:
    scene.frame_set(frame)
    pose(frame)
    scene.render.filepath = os.path.join(frames_dir, f"f_{frame:05d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"WIBE_FRAME {frame}", flush=True)
