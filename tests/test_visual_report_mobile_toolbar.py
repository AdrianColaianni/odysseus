from bs4 import BeautifulSoup

from src.visual_report import generate_visual_report


def test_hide_toolbar_is_an_export_menu_option_not_a_close_button():
    soup = BeautifulSoup(
        generate_visual_report("Toolbar report", "## Findings\n\nBody."),
        "html.parser",
    )

    hide_button = soup.select_one("#export-menu > #btn-hide-toolbar")
    assert hide_button is not None
    assert soup.select_one(".toolbar > .toolbar-close") is None
