"""Optional OCR for scanned pages that carry no embedded text layer.

A scanned page (image only) otherwise indexes as empty text. When OCR is
enabled, such a page is rasterized (PyMuPDF) and run through RapidOCR — an ONNX
engine with no system dependencies — to recover its text. OCR text is
machine-generated: callers tag it ``textSource="ocr"`` with a confidence so it
is treated as a pointer to the native page, never as filed evidence.

RapidOCR is an **optional** dependency: install the ``ocr`` extra
(``uv add rapidocr-onnxruntime numpy`` / ``pip install 'lawnlord[ocr]'``). The
engine and its models load once on first call and are reused; rendering uses a
fixed DPI so output is reproducible.

GPU (CUDA) acceleration is opt-in via ``make_ocr(use_gpu=True)`` / the CLI
``--gpu`` flag, and needs the CUDA build of ONNX Runtime plus the CUDA 12 /
cuDNN 9 runtime libraries (rapidocr-onnxruntime hard-depends on the CPU
``onnxruntime``, so this is a manual swap rather than a packaged extra)::

    uv pip uninstall onnxruntime
    uv pip install onnxruntime-gpu nvidia-cudnn-cu12 nvidia-cublas-cu12 \
        nvidia-cuda-runtime-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
        nvidia-cusparse-cu12 nvidia-cuda-nvrtc-cu12 nvidia-nvjitlink-cu12

``make_ocr`` calls ``onnxruntime.preload_dlls()`` to load those libraries from
the pip wheels (no ``LD_LIBRARY_PATH`` needed) and falls back to CPU with a
warning if CUDA is unavailable.
"""

from __future__ import annotations

from typing import Callable

import fitz

DEFAULT_OCR_DPI = 300

# An OCR backend: given a page, return (recovered_text, mean_confidence|None).
OcrFn = Callable[[fitz.Page], "tuple[str, float | None]"]


def _cuda_available() -> bool:
    """True if ONNX Runtime can offer the CUDA provider here. Loads the CUDA/
    cuDNN libraries from the installed NVIDIA pip wheels (preload_dlls) so no
    LD_LIBRARY_PATH is required."""
    try:
        import onnxruntime as ort
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def make_ocr(dpi: int = DEFAULT_OCR_DPI, use_gpu: bool = False) -> OcrFn:
    """Return an ``ocr(page) -> (text, confidence)`` callable backed by RapidOCR.

    With ``use_gpu=True`` the engine runs on the CUDA provider when available
    (requires ``onnxruntime-gpu`` + CUDA 12 / cuDNN 9, e.g. the ``nvidia-*-cu12``
    wheels); if CUDA is unavailable it warns and falls back to CPU. Raises a
    clear error if the optional OCR dependency itself is missing. The engine
    loads its models once (on construction) and is reused across pages.
    """
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires the optional 'ocr' extra: install rapidocr-onnxruntime "
            "and numpy (e.g. `uv add rapidocr-onnxruntime numpy` or "
            "`pip install 'lawnlord[ocr]'`)."
        ) from exc

    cuda = bool(use_gpu) and _cuda_available()
    if use_gpu and not cuda:
        from .console import console
        console.print(
            "[yellow]GPU OCR requested but CUDAExecutionProvider is unavailable;"
            " falling back to CPU. Install onnxruntime-gpu + CUDA 12 / cuDNN 9"
            " (the nvidia-*-cu12 wheels).[/]"
        )
    engine = RapidOCR(det_use_cuda=cuda, cls_use_cuda=cuda, rec_use_cuda=cuda)

    def ocr(page: fitz.Page) -> tuple[str, float | None]:
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if pix.n == 4:  # drop alpha; the engine wants RGB/grayscale
            img = img[:, :, :3]
        result, _ = engine(img)
        if not result:
            return "", None
        lines = [line[1] for line in result]
        confidences = [float(line[2]) for line in result if line[2] is not None]
        text = "\n".join(lines)
        confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )
        return text, confidence

    return ocr
