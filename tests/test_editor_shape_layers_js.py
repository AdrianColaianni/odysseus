import json
import textwrap
from pathlib import Path
from tests.helpers.node import run_node_module


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "static/js/editor/shape-layer.js").as_uri()


def run_node(body: str):
    script = textwrap.dedent(
        f"""
        import {{ normalizeShapeData, rasterizeShapeLayer, renderShapeLayer }} from {json.dumps(MODULE)};
        let id = 0;
        function canvas(tag='canvas') {{
          const value = {{tag, width:0, height:0, draws:[], fills:0, strokes:0}};
          const ctx = {{
            imageSmoothingEnabled:false, imageSmoothingQuality:'low',
            beginPath() {{}}, rect() {{}}, roundRect() {{}}, ellipse() {{}}, moveTo() {{}},
            lineTo() {{}}, closePath() {{}}, translate() {{}}, rotate() {{}}, scale() {{}},
            fill() {{ value.fills += 1; }}, stroke() {{ value.strokes += 1; }},
            drawImage(...args) {{ value.draws.push(args.map(item => item?.tag || item)); }},
            createLinearGradient(...args) {{
              value.gradient = args;
              globalThis.lastGradientCanvas = value;
              return {{addColorStop: (...stop) => (value.gradientStops = [...(value.gradientStops || []), stop])}};
            }},
            clearRect() {{}},
          }};
          value.getContext = () => ctx;
          return value;
        }}
        globalThis.document = {{createElement:() => {{
          const created = canvas(`canvas-${{++id}}`);
          globalThis.lastCreatedCanvas = created;
          return created;
        }}}};
        {body}
        """
    )
    return run_node_module(script)


def test_shape_renderer_keeps_editable_metadata_and_builds_cache():
    result = run_node(
        """
        const target = canvas('target');
        const layer = {canvas:target, ctx:target.getContext('2d'), shape:{
          type:'polygon', width:180, height:120, sides:6, fillColor:'#ff0000',
          strokeColor:'#001122', strokeWidth:4, cornerRadius:8,
          transform:{scaleX:1.5, scaleY:2, rotation:20, flipH:true},
        }};
        renderShapeLayer(layer);
        console.log(JSON.stringify({kind:layer.kind, shape:layer.shape, size:[layer.canvas.width, layer.canvas.height]}));
        """
    )
    assert result["kind"] == "shape"
    assert result["shape"]["type"] == "polygon"
    assert result["shape"]["sides"] == 6
    assert result["shape"]["transform"]["flipH"] is True
    assert result["size"][0] > 180
    assert result["size"][1] > 120


def test_shape_normalization_and_rasterization_are_bounded():
    result = run_node(
        """
        const value = normalizeShapeData({type:'unknown', width:-4, height:0, sides:99, strokeWidth:-1});
        const layer = {kind:'shape', shape:value};
        console.log(JSON.stringify({value, changed:rasterizeShapeLayer(layer), layer}));
        """
    )
    assert result["value"]["type"] == "rectangle"
    assert result["value"]["width"] == 1
    assert result["value"]["height"] == 1
    assert result["value"]["sides"] == 24
    assert result["value"]["strokeWidth"] == 0
    assert result["changed"] is True
    assert result["layer"] == {"kind": "raster", "shape": None}


def test_shape_gradient_is_rendered_without_losing_editable_metadata():
    result = run_node(
        """
        const target = canvas('target');
        const layer = {canvas:target, ctx:target.getContext('2d'), shape:{
          type:'rectangle', width:100, height:80, fillType:'linear-gradient',
          gradientStart:'#ff0000', gradientEnd:'#0000ff', gradientAngle:35,
        }};
        renderShapeLayer(layer);
        console.log(JSON.stringify({shape:layer.shape, gradient:lastGradientCanvas.gradient, stops:lastGradientCanvas.gradientStops}));
        """
    )
    assert result["shape"]["fillType"] == "linear-gradient"
    assert result["shape"]["gradientAngle"] == 35
    assert result["stops"][-1] == [1, "#0000ff"]
