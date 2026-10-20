from tests.helpers.node import run_node_module


def test_callback_actions_are_sorted_by_their_labels() -> None:
    order = run_node_module(
        """
        import { orderActionMenuItems } from './static/js/actionMenuOrder.js';
        const callback = () => {};
        const items = ['Delete', 'Archive', 'Copy', 'Favorite', 'Select', 'Rename', 'Open', 'Cancel']
          .map(label => ({ label, action: callback }));
        console.log(JSON.stringify(orderActionMenuItems(items).map(item => item.label)));
        """
    )
    assert order == ["Open", "Rename", "Favorite", "Copy", "Select", "Archive", "Delete", "Cancel"]
