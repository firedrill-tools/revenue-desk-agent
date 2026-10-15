"""Verify the bundled dataset and model-free CLI outside the checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

wheel, = Path("dist").glob("*.whl")
environment = {key:value for key,value in os.environ.items() if not key.startswith("OPENAI_")}
with ZipFile(wheel) as archive:
    assert "revenue_desk/sample_data/manifest.json" in archive.namelist()
    assert len([name for name in archive.namelist() if name.startswith("revenue_desk/sample_data/") and name.endswith(".json")]) == 11
    with TemporaryDirectory(prefix="revenue-desk-wheel-") as directory:
        archive.extractall(directory)
        script = '''
from pathlib import Path
import sys
sys.path.insert(0,sys.argv[1])
from revenue_desk import cli
assert Path(cli.__file__).is_relative_to(Path(sys.argv[1]))
assert cli.main(["--list-cases"]) == 0
raise SystemExit(cli.main(["--init-case","busy","--workspace",str(Path(sys.argv[1])/"workspace.json")]))
'''
        checked = subprocess.run([sys.executable,"-c",script,directory],cwd=directory,env=environment,
                                 text=True,capture_output=True,check=True)
        listed, initialized = [json.loads(line) for line in checked.stdout.splitlines()]
        assert listed["case_count"] == 10 and listed["version"] == "2.0.0"
        assert initialized["case_id"] == "busy" and initialized["model_called"] is False
        state = json.loads((Path(directory)/"workspace.json").read_text())
        assert len(state["accounts"]) == 12 and len(state["invoices"]) == 23 and len(state["requests"]) == 2
print("Packaged CLI validates ten cases and initializes the busy workspace outside the checkout; no model called.")
