"""Small-object inference preserves source coordinates and bounded CPU work."""
from unittest.mock import Mock

import numpy as np
import pytest

from botanika.core.settings import AppSettings
from botanika.vision.detection import BoundingBox, Detection, DetectorInferenceError
from botanika.vision.weeds import WeedService
from botanika.vision.weeds.service import _tile_intervals


def test_tiles_cover_landscape_portrait_and_tiny_axes():
    for length, count in [(1920, 3), (1080, 2), (3, 3), (1, 2)]:
        intervals = _tile_intervals(length, count)
        assert intervals[0][0] == 0
        assert intervals[-1][1] == length
        assert all(0 <= start < end <= length for start, end in intervals)
        assert all(a[1] >= b[0] for a, b in zip(intervals, intervals[1:]))


@pytest.mark.parametrize('shape', [(900, 1200, 3), (1200, 900, 3)])
def test_tiles_restore_coordinates_and_suppress_full_frame_duplicates(shape):
    height, width = shape[:2]
    columns, rows = (3, 2) if width >= height else (2, 3)
    left, right = _tile_intervals(width, columns)[-1]
    top, bottom = _tile_intervals(height, rows)[-1]
    source_box = BoundingBox(left + 10, top + 20, left + 60, top + 70)
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.7, source_box)], [], [], [], [], [],
        [Detection(0, 'weed', 0.9, BoundingBox(10, 20, 60, 70))],
    ]
    service = WeedService(AppSettings(), detector=detector)
    result = service.detect_image(np.zeros(shape, dtype=np.uint8))
    assert detector.detect.call_count == 7
    assert len(result['detections']) == 1
    detection = result['detections'][0]
    assert detection['confidence'] == 0.9
    assert detection['box'] == dict(x1=source_box.x1, y1=source_box.y1,
                                    x2=source_box.x2, y2=source_box.y2)
    assert detector.detect.call_args.args[0].shape == (bottom - top, right - left, 3)


def test_small_images_use_one_pass_and_reject_unsupported_or_weak_boxes():
    detector = Mock()
    detector.detect.return_value = [
        Detection(0, 'weed', 0.8, BoundingBox(10, 20, 30, 40)),
        Detection(0, 'weed', 0.1, BoundingBox(40, 50, 60, 70)),
        Detection(1, 'crop', 0.9, BoundingBox(70, 80, 90, 100)),
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((480, 640, 3), dtype=np.uint8))
    assert detector.detect.call_count == 1
    assert len(result['detections']) == 1


def test_failed_tile_does_not_report_partial_success():
    detector = Mock()
    detector.detect.side_effect = [[], DetectorInferenceError('tile failed')]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert result['status'] == 'unavailable'
    assert result['detections'] == []


def test_empty_image_is_rejected_before_inference():
    detector = Mock()
    with pytest.raises(ValueError, match='input'):
        WeedService(AppSettings(), detector=detector).detect_image(
            np.zeros((0, 640, 3), dtype=np.uint8))
    detector.detect.assert_not_called()


def test_dense_patch_fragments_do_not_inflate_count():
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.7, BoundingBox(0, 0, 1200, 900))],
        *[[Detection(0, 'weed', 0.9, BoundingBox(0, 0, 430, 470))]] * 6,
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 1
    assert result['detections'][0]['box']['x2'] == 1200


def test_boundary_fragments_are_suppressed_when_whole_frame_covers_them():
    """A broad whole-frame result must own clipped tile duplicates."""
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.58, BoundingBox(5, 100, 1200, 897))],
        [Detection(0, 'weed', 0.94, BoundingBox(0, 0, 435, 479))],
        [],
        [Detection(0, 'weed', 0.91, BoundingBox(0, 4, 435, 476))],
        [], [], [],
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 1
    assert result['detections'][0]['box']['x1'] == 5
    assert result['detections'][0]['box']['y1'] == 100


def test_partially_overlapping_confident_parent_does_not_swallow_neighbor():
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.95, BoundingBox(100, 0, 600, 500))],
        [Detection(0, 'weed', 0.90, BoundingBox(0, 0, 320, 320))],
        [], [], [], [], [],
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 2


def test_weak_parent_does_not_swallow_non_edge_neighbor():
    """Confidence alone cannot turn an overlap into a duplicate."""
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.40, BoundingBox(100, 0, 600, 500))],
        [Detection(0, 'weed', 0.90, BoundingBox(0, 0, 320, 320))],
        [], [], [], [], [],
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 2


def test_invalid_parent_never_suppresses_valid_tile_detection():
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.20, BoundingBox(0, 0, 500, 500))],
        [Detection(0, 'weed', 0.90, BoundingBox(0, 0, 320, 320))],
        [], [], [], [], [],
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 1
    assert result['detections'][0]['confidence'] == 0.90


def test_nonfinite_parent_never_suppresses_valid_tile_detection():
    detector = Mock()
    detector.detect.side_effect = [
        [Detection(0, 'weed', 0.90, BoundingBox(float('nan'), 0, 500, 500))],
        [Detection(0, 'weed', 0.90, BoundingBox(0, 0, 320, 320))],
        [], [], [], [], [],
    ]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 1
    assert result['detections'][0]['confidence'] == 0.90


def test_small_weed_missed_in_full_frame_is_recovered():
    detector = Mock()
    detector.detect.side_effect = [[], [Detection(0, 'weed', 0.8,
        BoundingBox(10, 20, 30, 40))], [], [], [], [], []]
    result = WeedService(AppSettings(), detector=detector).detect_image(
        np.zeros((900, 1200, 3), dtype=np.uint8))
    assert len(result['detections']) == 1
    assert result['detections'][0]['box'] == dict(x1=10, y1=20, x2=30, y2=40)
