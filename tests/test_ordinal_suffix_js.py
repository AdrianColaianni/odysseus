"""Pin the ordinal-suffix helper used by the monthly-schedule label in tasks.js.

_scheduleLabel built the suffix with `d === 1 ? 'st' : d === 2 ? 'nd' : ...`,
which only handles single digits, so a monthly task on day 21/22/23/31 rendered
"Monthly on 21th"/"22th"/"23th"/"31th". The shared ordinalSuffix() fixes this.
"""
from tests.helpers.node import run_node_module


def test_ordinal_suffixes_for_days_of_month():
    labels = run_node_module("""
    import { ordinalSuffix } from './static/js/util/ordinal.js';
    console.log(JSON.stringify([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31].map(n => n + ordinalSuffix(n))));
    """)
    assert labels == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "31st",
    ]
