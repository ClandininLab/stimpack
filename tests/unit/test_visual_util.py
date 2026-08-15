"""Unit tests for stimpack.visual_stim.util (the movie-recording QImage converter)."""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")
pytest.importorskip("PyQt6")

from PyQt6.QtGui import QImage, qRgba

from stimpack.visual_stim.util import qimage2ndarray

pytestmark = pytest.mark.unit


def test_qimage2ndarray_shape_and_rgba_order():
    # Regression (#14): the old converter used Qt5 APIs (convertToFormat(int), byteCount) that raise
    # under PyQt6. It should return an (H, W, 4) uint8 array in R, G, B, A order.
    img = QImage(3, 2, QImage.Format.Format_ARGB32)  # a different source format, to exercise the convert
    img.fill(qRgba(10, 20, 30, 255))                 # R=10 G=20 B=30 A=255

    arr = qimage2ndarray(img)

    assert arr.dtype.name == "uint8"
    assert arr.shape == (2, 3, 4)                     # (height, width, RGBA)
    assert arr[0, 0].tolist() == [10, 20, 30, 255]    # R, G, B, A
    assert (arr[:, :, 2] == 30).all()                 # the movie path grabs [:, :, 2] as "blue"


def test_qimage2ndarray_does_not_alias_the_qimage():
    # The result must be an independent copy (the QImage buffer is freed after the call).
    img = QImage(2, 2, QImage.Format.Format_RGBA8888)
    img.fill(qRgba(1, 2, 3, 255))
    arr = qimage2ndarray(img)
    assert arr.flags["OWNDATA"] or arr.base is None
