from tests.helpers.node import ROOT, run_node_module

_MODULE = ROOT / "static" / "js" / "presets.js"


def _load_values():
    return run_node_module(f"""
    globalThis.localStorage = {{
      getItem(key) {{
        return {{
          broken: '{{',
          list: '[]',
          object: '{{"session":"Socrates"}}',
        }}[key] ?? null;
      }},
    }};
    const presets = await import('{_MODULE.as_posix()}');
    console.log(JSON.stringify({{
      brokenArray: presets.loadStoredArray('broken'),
      wrongArray: presets.loadStoredArray('object'),
      brokenObject: presets.loadStoredObject('broken'),
      wrongObject: presets.loadStoredObject('list'),
      object: presets.loadStoredObject('object'),
    }}));
    """)


def test_preset_storage_helpers_fall_back_for_bad_values():
    assert _load_values() == {
        "brokenArray": [],
        "wrongArray": [],
        "brokenObject": {},
        "wrongObject": {},
        "object": {"session": "Socrates"},
    }
