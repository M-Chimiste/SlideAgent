from pathlib import Path
import subprocess

from app.config import Settings


class NodePptxGenRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.script_path = Path(__file__).parent / "pptxgen_runner.js"

    def render_deck(self, deck_json_path: Path, output_path: Path) -> None:
        command = [
            "node",
            self.script_path.as_posix(),
            deck_json_path.as_posix(),
            output_path.as_posix(),
        ]
        subprocess.run(command, check=True)
