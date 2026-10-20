from pathlib import Path
import re

from tests.helpers.node import run_node_module

ROOT = Path(__file__).parents[1]


def test_same_local_model_keeps_distinct_endpoint_keys():
    source = (ROOT / 'static/js/modelPicker.js').read_text()
    helper = re.search(r'function _pickerModelKey\(m\) \{.*?\n\}', source, re.S).group()
    keys = run_node_module(helper + '''
      const a = _pickerModelKey({mid:'same-model',endpointId:'normal'});
      const b = _pickerModelKey({mid:'same-model',endpointId:'preview'});
      const again = _pickerModelKey({mid:'same-model',endpointId:'normal'});
      console.log(JSON.stringify([a, b, again]));
    ''')
    assert keys == ['normal::same-model', 'preview::same-model', 'normal::same-model']
