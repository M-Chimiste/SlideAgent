from pathlib import Path
import shutil
import subprocess


class RenderingError(RuntimeError):
    pass


def ensure_render_tools() -> None:
    if shutil.which("soffice") is None:
        raise RenderingError("LibreOffice (soffice) is not available.")
    if shutil.which("pdftoppm") is None:
        raise RenderingError("poppler-utils (pdftoppm) is not available.")


def render_pptx_to_pdf(pptx_path: Path, output_dir: Path) -> Path:
    ensure_render_tools()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir.as_posix(),
                pptx_path.as_posix(),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        message = "LibreOffice PDF render failed."
        if details:
            message = f"{message} {details}"
        raise RenderingError(message) from exc
    pdf_path = output_dir / "render.pdf"
    if not pdf_path.exists():
        generated = list(output_dir.glob("*.pdf"))
        if not generated:
            raise RenderingError("PDF render failed.")
        pdf_path = generated[0]
    return pdf_path


def render_pptx_to_images(
    pptx_path: Path, output_dir: Path, dpi: int = 150
) -> list[Path]:
    ensure_render_tools()
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = render_pptx_to_pdf(pptx_path, output_dir)

    try:
        subprocess.run(
            [
                "pdftoppm",
                "-jpeg",
                "-r",
                str(dpi),
                pdf_path.as_posix(),
                (output_dir / "slide").as_posix(),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        message = "Poppler image render failed."
        if details:
            message = f"{message} {details}"
        raise RenderingError(message) from exc
    return sorted(output_dir.glob("slide-*.jpg"))
