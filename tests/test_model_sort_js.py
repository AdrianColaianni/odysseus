from tests.helpers.node import run_node_module


def test_model_sort_helpers_ignore_non_arrays():
    values = run_node_module(
        """
        import { sortModelIds, sortModelObjects } from './static/js/modelSort.js';
        console.log(JSON.stringify({
          idsObject: sortModelIds({bad: true}),
          idsString: sortModelIds('llama'),
          objectsNull: sortModelObjects(null),
          objectsObject: sortModelObjects({bad: true})
        }));
        """
    )

    assert values == {
        "idsObject": [],
        "idsString": [],
        "objectsNull": [],
        "objectsObject": [],
    }


def test_model_sort_helpers_keep_valid_arrays():
    values = run_node_module(
        """
        import { sortModelIds, sortModelObjects } from './static/js/modelSort.js';
        console.log(JSON.stringify({
          ids: sortModelIds(['zeta/10', 'alpha/2', 'alpha/11']),
          objects: sortModelObjects([{id: 'zeta/10'}, {id: 'alpha/2'}]).map(m => m.id)
        }));
        """
    )

    assert values == {
        "ids": ["alpha/2", "zeta/10", "alpha/11"],
        "objects": ["alpha/2", "zeta/10"],
    }
