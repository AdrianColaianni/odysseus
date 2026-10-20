from tests.helpers.node import run_node_module


def test_censor_pref_falls_back_when_storage_throws():
    values = run_node_module(
        """
        globalThis.localStorage = {
          getItem() { throw new Error('blocked'); }
        };
        const { _prefEnabled } = await import('./static/js/censor.js');
        console.log(JSON.stringify({ enabled: _prefEnabled() }));
        """
    )

    assert values == {"enabled": False}


def test_censor_pref_reads_enabled_flag():
    values = run_node_module(
        """
        globalThis.localStorage = {
          getItem(key) { return key === 'odysseus-sensitive-blur' ? 'on' : null; }
        };
        const { _prefEnabled } = await import('./static/js/censor.js');
        console.log(JSON.stringify({ enabled: _prefEnabled() }));
        """
    )

    assert values == {"enabled": True}
