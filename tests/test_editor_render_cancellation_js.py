import json
import textwrap
from pathlib import Path
from tests.helpers.node import run_node_module


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "static/js/editor/render-cancellation.js").as_uri()


def run_node(body: str):
    script = textwrap.dedent(
        f"""
        import {{createRenderGeneration}} from {json.dumps(MODULE)};
        {body}
        """
    )
    return run_node_module(script)


def test_new_render_generation_invalidates_previous_work():
    result = run_node(
        """
        const generations = createRenderGeneration();
        const first = generations.begin();
        const second = generations.begin();
        console.log(JSON.stringify({first:first.isCurrent(), second:second.isCurrent()}));
        """
    )
    assert result == {"first": False, "second": True}


def test_cancel_only_invalidates_the_cancelled_generation():
    result = run_node(
        """
        const generations = createRenderGeneration();
        const render = generations.begin();
        render.cancel();
        const next = generations.begin();
        console.log(JSON.stringify({cancelled:render.isCurrent(), next:next.isCurrent()}));
        """
    )
    assert result == {"cancelled": False, "next": True}
