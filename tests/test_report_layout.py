"""The chart report's main column is centred and fills the page up to 1100px, at desktop and phone widths."""

from pathlib import Path

import pytest

from poker_analyzer import db
from poker_analyzer.chart import compare, load_charts
from poker_analyzer.chart_report import build_html
from poker_analyzer.importer import import_folder
from poker_analyzer.preflop import hero_decisions
from poker_analyzer.preflop_report import report_meta

sync_api = pytest.importorskip("playwright.sync_api")

FIXTURES = Path(__file__).parent / "fixtures"
WIDTHS = [1366, 1100, 400]

MEASURE = """(openDetails) => {
  if (openDetails) document.querySelectorAll('details').forEach(d => d.open = true);
  const vw = document.documentElement.clientWidth, box = document.querySelector('main').getBoundingClientRect();
  // Each section, and each table in the details, against the content width of the box it sits in.
  const inner = e => { const s = getComputedStyle(e);
    return e.getBoundingClientRect().width - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight)
           - parseFloat(s.borderLeftWidth) - parseFloat(s.borderRightWidth); };
  const blocks = [...document.querySelectorAll('main > section, main > details, details.all > section, details.all .table-wrap > table')]
    .filter(e => e.getBoundingClientRect().width > 0);
  const shortfall = Math.max(0, ...blocks.map(e => inner(e.parentElement) - e.getBoundingClientRect().width));
  return {vw, scroll: document.documentElement.scrollWidth, left: box.left, right: vw - box.right, width: box.width,
          shortfall};
}"""


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("layout")
    conn = db.connect(tmp / "test.db")
    for folder in ("chart", "preflop"):
        import_folder(conn, FIXTURES / folder)
    html = build_html(compare(hero_decisions(conn), load_charts()), load_charts(), report_meta(conn, tmp / "test.db"))
    conn.close()
    path = tmp / "preflop_vs_chart.html"
    path.write_text(html, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser not downloaded: python -m playwright install chromium
            pytest.skip(f"Chromium for Playwright isn't installed: {e}")
        yield b
        b.close()


@pytest.mark.parametrize("open_details", [False, True], ids=["details closed", "details open"])
@pytest.mark.parametrize("width", WIDTHS)
def test_main_column_is_centred_and_fills_the_width(browser, report, width, open_details):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.goto(report.as_uri())
    m = page.evaluate(MEASURE, open_details)
    page.close()
    assert abs(m["left"] - m["right"]) <= 5, m  # equal space on both sides
    assert m["width"] >= min(1100, m["vw"] - 32) - 0.5, m
    assert m["scroll"] <= m["vw"], m  # no sideways scrolling
    assert m["shortfall"] <= 0.5, m  # sections and tables fill the box they sit in
    print(f"{width}px, details {'open' if open_details else 'closed'}: {m}")
