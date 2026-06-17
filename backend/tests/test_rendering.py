import subprocess

import pytest

from app.services.rendering import RenderingError, render_pptx_to_pdf


def test_render_pptx_to_pdf_wraps_soffice_process_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.rendering.ensure_render_tools", lambda: None)

    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=134,
            cmd=args[0],
            stderr="Abort trap: 6",
        )

    monkeypatch.setattr("app.services.rendering.subprocess.run", fail_run)

    with pytest.raises(RenderingError, match="LibreOffice PDF render failed"):
        render_pptx_to_pdf(tmp_path / "deck.pptx", tmp_path / "preview")
