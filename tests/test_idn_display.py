import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_idn_converter_decodes_hostname_labels() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser helper regression test")

    helper = ROOT / "js" / "idn-display.js"
    script = f"""
require({json.dumps(str(helper))});
const convert = globalThis.hitchhikerIdn.toUnicodeHostname;
console.log(JSON.stringify([
  convert("akkoma.xn--pikabl-0xa.se"),
  convert("akkoma.xn--t8jzbl7g.jp"),
  convert("mastodon.xn--9cs231j0ji.xn--p8s937b.net"),
  convert("example.com"),
  convert("xn--invalid-.example")
]));
"""
    result = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        "akkoma.pikaböl.se",
        "akkoma.おったぺ.jp",
        "mastodon.韓國語.漢字.net",
        "example.com",
        "xn--invalid-.example",
    ]


def test_page_uses_unicode_only_for_visible_fallback_name() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    render_script = (ROOT / "js" / "render.js").read_text(encoding="utf-8")

    assert html.index('src="js/idn-display.js"') < html.index(
        'src="js/render.js"'
    )
    assert "name: manualName ?? displayHost" in render_script
    assert "nameLink.href = linkHref" in render_script
    assert "nameLink.title = host" in render_script
    assert 'nameLink.setAttribute("aria-label", `${nameText} (${host})`)' in render_script


@pytest.mark.parametrize(
    "workflow_path",
    [
        ".github/workflows/test.yml",
        ".github/workflows/update.yml",
    ],
)
def test_workflows_use_current_setup_python_action(workflow_path: str) -> None:
    workflow = (ROOT / workflow_path).read_text(encoding="utf-8")

    assert "actions/setup-python@v7" in workflow
    assert "actions/setup-python@v5" not in workflow
