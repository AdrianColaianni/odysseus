from tests.helpers.node import run_node_module


def test_calendar_date_helpers_ignore_non_string_inputs():
    values = run_node_module(
        """
        import { _addDays, _shiftDT, _localDateOf } from './static/js/calendar/utils.js';
        console.log(JSON.stringify({
          addNull: _addDays(null, 1),
          addObject: _addDays({bad: true}, 1),
          shiftNull: _shiftDT(null, 1),
          shiftObject: _shiftDT({bad: true}, 1),
          localNull: _localDateOf(null),
          localNumber: _localDateOf(123)
        }));
        """
    )

    assert values == {
        "addNull": "",
        "addObject": "",
        "shiftNull": "",
        "shiftObject": "",
        "localNull": "",
        "localNumber": "",
    }


def test_calendar_date_helpers_keep_valid_strings():
    values = run_node_module(
        """
        import { _addDays, _shiftDT, _localDateOf } from './static/js/calendar/utils.js';
        console.log(JSON.stringify({
          add: _addDays('2026-06-01', 2),
          shift: _shiftDT('2026-06-01T10:30:00', 1),
          local: _localDateOf('2026-06-01T23:30:00Z')
        }));
        """
    )

    assert values["add"] == "2026-06-03"
    assert values["shift"] == "2026-06-02T10:30:00"
    assert isinstance(values["local"], str)
    assert len(values["local"]) == 10
