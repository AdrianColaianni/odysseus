from tests.helpers.node import run_node_module


def test_calendar_readable_text_color_prefers_dark_ink_for_pastels():
    values = run_node_module(
        """
        import { _calReadableTextColor } from './static/js/calendar/utils.js';
        console.log(JSON.stringify({
          blue: _calReadableTextColor('#b0d7f7'),
          yellow: _calReadableTextColor('#f2dfbd'),
          shortHex: _calReadableTextColor('#abc')
        }));
        """
    )

    assert values == {
        "blue": "#111820",
        "yellow": "#111820",
        "shortHex": "#111820",
    }


def test_calendar_readable_text_color_keeps_light_text_for_dark_colors():
    values = run_node_module(
        """
        import { _calReadableTextColor } from './static/js/calendar/utils.js';
        console.log(JSON.stringify({
          navy: _calReadableTextColor('#1f3552'),
          red: _calReadableTextColor('#78252d'),
          variable: _calReadableTextColor('var(--accent)')
        }));
        """
    )

    assert values == {
        "navy": "#ffffff",
        "red": "#ffffff",
        "variable": "var(--fg)",
    }
