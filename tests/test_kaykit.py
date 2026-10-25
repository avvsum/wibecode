"""KayKit choices extend the spec without changing existing dialogue roles."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "kaykit"


def test_legacy_spec_keeps_original_studio_and_cast(api, payload):
    spec = api.parse_spec(json.dumps(payload))
    assert (spec.environment, spec.cast) == ("studio", "classic")


@pytest.mark.parametrize("environment", ["studio", "room", "forest", "dungeon", "space", "city"])
@pytest.mark.parametrize("cast", ["classic", "knight_mage", "rogue_duo", "barbarian_mage", "ranger_knight"])
def test_environment_and_cast_keep_dialogue_slots(api, environment, cast):
    spec = api.parse_spec(json.dumps({
        "duration": 2, "render_mode": "3d", "environment": environment, "cast": cast,
        "scenes": [
            {"type": "say", "who": "robot", "shot": "wide", "text": "Привет", "start": 0, "end": 1},
            {"type": "say", "who": "girl", "shot": "close", "text": "И тебе", "start": 1, "end": 2},
        ],
    }))
    assert (spec.environment, spec.cast) == (environment, cast)
    assert [scene.who for scene in spec.scenes] == ["robot", "girl"]


@pytest.mark.parametrize("field", ["environment", "cast"])
@pytest.mark.parametrize("value", [None, "", "FOREST", 1, "unknown"])
def test_invalid_choice_has_field_and_allowed_values(api, payload, field, value):
    payload.update(render_mode="3d", **{field: value})
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(json.dumps(payload))
    message = str(caught.value)
    assert field in message
    assert ("studio" if field == "environment" else "classic") in message


def test_bundled_gltf_textures_and_buffers_are_available_offline():
    models = list(ASSETS.rglob("*.gltf"))
    assert models, "KayKit assets must be included in the checkout"
    for model in models:
        document = json.loads(model.read_text(encoding="utf-8"))
        for item in document.get("buffers", []) + document.get("images", []):
            uri = item.get("uri", "")
            if uri and not uri.startswith("data:"):
                assert "://" not in uri, f"{model}: resource must be local: {uri}"
                assert (model.parent / unquote(uri)).is_file(), f"{model}: missing {uri}"


def test_environments_have_balanced_detail_and_all_models_are_bundled(api):
    from src.core.render3d.kaykit_scene import CAST_MODELS, ENVIRONMENT_LAYOUTS, asset_path

    assert set(ENVIRONMENT_LAYOUTS) == set(api.ENVIRONMENTS) - {"studio"}
    assert set(CAST_MODELS) == set(api.CASTS) - {"classic"}
    counts = [len(layout) for layout in ENVIRONMENT_LAYOUTS.values()]
    assert min(counts) >= 24
    assert max(counts) / min(counts) <= 1.25
    for layout in ENVIRONMENT_LAYOUTS.values():
        assert len({(pack, model) for pack, model, *_ in layout}) >= 10
        assert sum(size >= 1 for _, _, _, _, size, _ in layout) >= 8
        assert sum(size < 1 for _, _, _, _, size, _ in layout) >= 16
        for pack, model, *_ in layout:
            assert asset_path(ASSETS, pack, model).is_file()
    for models in CAST_MODELS.values():
        assert len(set(models)) == 2
        for model in models:
            assert asset_path(ASSETS, "adventurers", model).is_file()
    assert asset_path(ASSETS, "animations", "Rig_Medium_General").is_file()


@pytest.mark.integration
@pytest.mark.blender
def test_classic_cast_survives_kaykit_forest(tmp_path):
    """Exercise the Blender script: a new world must not silently replace the cast."""
    blender = os.environ.get("WIBECODE_BLENDER") or shutil.which("blender")
    assert blender, "Для теста blender нужен Blender в PATH или WIBECODE_BLENDER"
    script = ASSETS.parents[1] / "src" / "core" / "render3d" / "blender_scene.py"
    job = tmp_path / "job.json"
    job.write_text(json.dumps({
        "environment": "forest", "cast": "classic", "assets_dir": str(ASSETS),
        "fps": 30, "width": 180, "height": 320, "frames_dir": str(tmp_path),
        "frames": [1], "lines": [{"who": "robot", "shot": "wide", "first": 1, "last": 1}],
    }), encoding="utf-8")
    report = tmp_path / "cast.json"
    wrapper = tmp_path / "check_cast.py"
    wrapper.write_text(
        "import bpy, json, runpy, sys\n"
        f"sys.argv = [{str(script)!r}, '--', {str(job)!r}]\n"
        f"result = runpy.run_path({str(script)!r})\n"
        "roles = {role: parts['root'].name for role, parts in result['CHARACTERS'].items()}\n"
        "assert all(name in bpy.data.objects for name in roles.values())\n"
        "assert 'KayKit_diorama_base' in bpy.data.objects\n"
        f"open({str(report)!r}, 'w').write(json.dumps(roles))\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(wrapper)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    assert process.returncode == 0, process.stdout[-3000:] + process.stderr[-3000:]
    assert json.loads(report.read_text()) == {"robot": "robot", "girl": "girl"}
    assert (tmp_path / "f_00001.png").stat().st_size > 0
