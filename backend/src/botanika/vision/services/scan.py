"""Scan coordinator that owns the Pi Camera, detector, lock-on, and classifier.

The Phase 6 service wraps the verified Phase 1–5 modules behind one thread that
owns the camera handle, publishes letterboxed preview frames, and emits atomic
scan snapshots.  Commands (manual capture, box selection, retake, cancellation,
local-image fallback) are exchanged through thread-safe flags so the frame loop
never races with API handlers.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from botanika.core.settings import AppSettings
from botanika.hardware.camera import CameraConfig, CameraError, CameraOwner, FrameReadError
from botanika.vision.classification import (
    CampusFewShotClassifier,
    CancellationToken,
    CompactSpeciesClassifier,
    ClassificationPipeline,
    SpeciesClassifier,
    UnavailableSpeciesClassifier,
)
from botanika.vision.detection import (
    BoundingBox,
    Detection,
    DetectorError,
    ModelManifest,
    YoloOnnxDetector,
)
from botanika.vision.quality import (
    CaptureResult,
    CropStore,
    LockOnConfig,
    LockOnEngine,
    LockOnState,
    LockOnUpdate,
    QualityConfig,
    evaluate_crop,
)
from .events import EventHub
from .overlay import OverlayTransform
from .preview import (
    PreviewBuffer,
    PreviewFrame,
    encode_jpeg,
    letterbox_frame,
    placeholder_frame,
)
from .snapshot import ScanSnapshot, snapshot_from_update


LOGGER = logging.getLogger("botanika.phase6.scan")
CAMERA_CONFIG = CameraConfig(window_name="Botanika Kiosk")
MANUAL_FRAME_LABEL = "manual central view"
MANUAL_FRAME_CLASS_ID = -1
# Leave a small safety inset so a manual tree/plant view can pass the edge
# quality gate while still retaining almost the entire camera frame.  The
# detector remains detection-only: this box is created only after the
# operator presses the manual-capture hotkey/button.
MANUAL_FRAME_INSET_RATIO = 0.04


@dataclass(slots=True)
class FallbackImage:
    """A user-selected local image held only in memory during its session."""

    image: np.ndarray
    name: str
    transform: OverlayTransform
    detections: list[Detection]
    created_at: float


def _crop_region(frame: np.ndarray, box) -> np.ndarray:
    """Extract an in-memory crop region without ever writing the source frame."""

    height, width = frame.shape[:2]
    x1 = max(0, min(width - 1, math.floor(box.x1)))
    y1 = max(0, min(height - 1, math.floor(box.y1)))
    x2 = max(x1 + 1, min(width, math.ceil(box.x2)))
    y2 = max(y1 + 1, min(height, math.ceil(box.y2)))
    return np.ascontiguousarray(frame[y1:y2, x1:x2])


def _detection_index(detections: tuple[Detection, ...], target: Detection | None) -> int | None:
    if target is None:
        return None
    for index, detection in enumerate(detections):
        if detection is target or (
            detection.label == target.label
            and detection.box == target.box
            and detection.class_id == target.class_id
        ):
            return index
    return None


class ScanService:
    """One background thread owns the Camera, detector, lock-on and classifier."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        classifier: SpeciesClassifier | None = None,
        camera_factory: Callable[[], object] | None = None,
        detector: YoloOnnxDetector | None = None,
        quality_config: QualityConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        use_production_classifier: bool | None = None,
    ) -> None:
        self.settings = settings
        self.preview_buffer = PreviewBuffer()
        self.events = EventHub(settings.event_backlog)
        self._clock = clock
        self._classifier_error: str | None = None
        if use_production_classifier is None:
            # A normal AppSettings instance is the Phase 6 runtime. The only
            # remaining stub path is the explicit Phase 5 compatibility
            # configuration used by old fixtures (a custom demo directory).
            use_production_classifier = not settings.legacy_demo_mode
        if classifier is not None:
            self._classifier = classifier
        elif use_production_classifier:
            try:
                campus_path = Path(settings.campus_classifier_model_path)
                if campus_path.is_file():
                    self._classifier = CampusFewShotClassifier(
                        campus_path,
                        settings.embedding_model_path,
                        settings.species_catalog_path,
                        acceptance_threshold=settings.acceptance_threshold,
                    )
                    LOGGER.info("Loaded campus few-shot classifier artifact %s", campus_path)
                else:
                    self._classifier = CompactSpeciesClassifier(
                        settings.classifier_model_path,
                        settings.species_catalog_path,
                        acceptance_threshold=settings.acceptance_threshold,
                    )
            except Exception as exc:
                self._classifier_error = str(exc)
                LOGGER.error("Species classifier unavailable: %s", exc)
                self._classifier = UnavailableSpeciesClassifier(str(exc))
        else:
            # Direct Phase 4/5 service fixtures can still exercise camera and
            # lock-on behavior without requiring a production model. The
            # application lifespan opts into the Phase 6 classifier explicitly.
            from botanika.vision.classification import DummyClassifier

            self._classifier = DummyClassifier()
        self._camera_factory = camera_factory
        self._detector_override = detector
        self._quality_config = quality_config or QualityConfig.from_file(settings.quality_config_path)
        self._crop_store = CropStore(
            settings.temp_crops_dir,
            padding_ratio=settings.crop_padding_ratio,
        )
        self._lock_config = LockOnConfig(
            eligible_labels=settings.eligible_labels,
            stable_checks=settings.stable_checks,
            minimum_appearance_similarity=settings.appearance_similarity,
            cooldown_frames=settings.cooldown_frames,
            crop_padding_ratio=settings.crop_padding_ratio,
            quality=self._quality_config,
        )

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state_lock = threading.RLock()
        self._restart_requested = False
        self._manual_capture_requested = False
        self._reset_requested = False
        self._cancel_requested = False
        self._selected_index: int | None = None
        self._fallback: FallbackImage | None = None
        self._pending_fallback: tuple[np.ndarray, str] | None = None
        self._fallback_capture_requested = False
        self._fallback_capture_index = 0
        self._fallback_clear_requested = False
        self._fallback_sequence = 0
        self._preview_sequence = 0
        self._classification_cancellation: CancellationToken | None = None
        self._external_pipeline = ClassificationPipeline(self._classifier)
        self._external_classification_lock = threading.Lock()
        self._external_capture: CaptureResult | None = None
        self._controller_mode = threading.Event()

        self._camera: CameraOwner | None = None
        self._detector: YoloOnnxDetector | None = None
        self._engine: LockOnEngine | None = None
        self._pipeline: ClassificationPipeline | None = None
        self._frame: np.ndarray | None = None
        self._session_id = "scan-initial"
        self._camera_error: str | None = None
        self._detector_error: str | None = None
        self._camera_running = False
        self._detector_loaded = False
        self._max_reconnect_attempts = 5
        self._retry_delay_seconds = 2.0

    # -- lifecycle -----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def camera_running(self) -> bool:
        with self._state_lock:
            return self._camera_running

    @property
    def detector_loaded(self) -> bool:
        with self._state_lock:
            return self._detector_loaded

    @property
    def camera_error(self) -> str | None:
        with self._state_lock:
            return self._camera_error

    @property
    def detector_error(self) -> str | None:
        with self._state_lock:
            return self._detector_error

    @property
    def classifier_version(self) -> str:
        return getattr(self._classifier, "classifier_version", "unknown")

    @property
    def classifier_stub(self) -> bool:
        return getattr(self._classifier, "is_stub", False) is not False

    @property
    def classifier_available(self) -> bool:
        return self._classifier_error is None and getattr(self._classifier, "deployment_ready", True)

    @property
    def classifier_error(self) -> str | None:
        if self._classifier_error is not None:
            return self._classifier_error
        return getattr(self._classifier, "deployment_blocker", None)

    @property
    def classifier_model(self) -> dict[str, object] | None:
        metadata = getattr(self._classifier, "metadata", None)
        if metadata is None:
            return None
        try:
            return metadata.to_dict()
        except AttributeError:
            return None

    def start(self) -> None:
        """Launch the owner thread and publish an initial placeholder preview."""

        if self.is_running:
            return
        placeholder = placeholder_frame(
            OverlayTransform.for_frame(
                CAMERA_CONFIG.width,
                CAMERA_CONFIG.height,
                self.settings.preview_width,
                self.settings.preview_height,
            )
        )
        self.preview_buffer.put(placeholder)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="botanika-scan", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._state_lock:
            if self._classification_cancellation is not None:
                self._classification_cancellation.cancel()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        if thread is not None and thread.is_alive():
            LOGGER.error("Scan owner thread did not stop within %.1f seconds", timeout)
            return
        self._thread = None

    def restart(self) -> None:
        """Clear the reconnect cap and ask the loop to try the camera again."""

        with self._state_lock:
            self._restart_requested = True
            self._camera_error = None

    def set_application_mode(self, mode: object) -> None:
        """Hand camera ownership to the paired browser when required.

        The Pi camera loop remains the SOLO owner. In paired mode it closes its
        resources and waits, so a browser crop cannot race a Pi capture or be
        overwritten by a later Pi-camera snapshot.
        """

        value = getattr(mode, "value", mode)
        paired = str(value).upper() == "NETWORKED_PAIRED"
        handoff = str(value).upper() != "SOLO"
        if handoff:
            self._controller_mode.set()
            with self._state_lock:
                if self._classification_cancellation is not None:
                    self._classification_cancellation.cancel()
            if paired:
                self._publish_controller_waiting()
        else:
            was_handoff = self._controller_mode.is_set()
            self._controller_mode.clear()
            if was_handoff:
                with self._state_lock:
                    self._restart_requested = True
                    self._camera_error = None
                self._publish_starting()

    set_mode = set_application_mode

    # -- operator commands ----------------------------------------------------

    def request_manual_capture(self) -> None:
        """Capture the selected/current target immediately on the next frame."""

        with self._state_lock:
            self._manual_capture_requested = True

    def request_select_box(self, index: int) -> bool:
        """Pin a detection box for tracking; return False when out of range."""

        latest = self.events.latest()
        if latest is None or index < 0 or index >= len(latest.detections):
            return False
        with self._state_lock:
            self._selected_index = index
            fallback = self._fallback
        if fallback is not None:
            self._publish_fallback(processing=False, hint="Local image target selected")
        return True

    def request_retake(self) -> None:
        """Discard the current result and return to detection (new session)."""

        with self._state_lock:
            self._reset_requested = True
            if self._classification_cancellation is not None:
                self._classification_cancellation.cancel()

    def request_cancel(self) -> None:
        """Cancel processing and return safely to detection."""

        with self._state_lock:
            self._cancel_requested = True
            if self._classification_cancellation is not None:
                self._classification_cancellation.cancel()

    def set_fallback_image(self, image: np.ndarray, name: str) -> None:
        """Use a user-selected local image instead of the live camera.

        The image is kept in memory only; the full frame is never persisted.
        """

        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(f"fallback image must be 3-channel, got {getattr(image, 'shape', None)!r}")
        if image.dtype != np.uint8 or min(image.shape[:2]) < 3:
            raise ValueError("fallback image must be an 8-bit image at least 3×3 pixels")
        with self._state_lock:
            self._pending_fallback = (np.ascontiguousarray(image.copy()), name)
            self._selected_index = None
            if self._classification_cancellation is not None:
                self._classification_cancellation.cancel()

    def clear_fallback(self) -> None:
        with self._state_lock:
            self._fallback_clear_requested = True
            if self._classification_cancellation is not None:
                self._classification_cancellation.cancel()

    def request_fallback_capture(self, index: int = 0) -> bool:
        with self._state_lock:
            fallback = self._fallback
            if fallback is None or index < 0 or index >= len(fallback.detections):
                return False
            self._fallback_capture_requested = True
            self._fallback_capture_index = index
        return True

    # -- accessors -----------------------------------------------------------

    def latest_snapshot(self) -> ScanSnapshot | None:
        return self.events.latest()

    def latest_preview(self) -> PreviewFrame | None:
        return self.preview_buffer.get()

    def latest_frame(self) -> np.ndarray | None:
        """Return a copy of the newest Pi frame for one still-image beta job."""

        with self._state_lock:
            if self._frame is None:
                return None
            return np.ascontiguousarray(self._frame.copy())

    def classify_external_crop(
        self,
        encoded_bytes: bytes,
        *,
        image: np.ndarray | None = None,
        request_id: str | None = None,
        controller_lease_id: str | None = None,
        commit_guard: Callable[[Callable[[], None]], None] | None = None,
        on_commit: Callable[[object], None] | None = None,
    ):
        """Classify one crop handed off by the paired browser.

        This deliberately bypasses the Pi camera/detector loop while reusing
        the same :class:`ClassificationPipeline` and classifier object.  The
        resulting capture is published as the latest authoritative snapshot so
        the existing library save route can persist it transactionally.
        """

        if not isinstance(encoded_bytes, (bytes, bytearray)) or not encoded_bytes:
            raise ValueError("external crop bytes must be non-empty")
        encoded = bytes(encoded_bytes)
        decoded = image
        if decoded is None:
            import cv2

            decoded = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
        if not isinstance(decoded, np.ndarray) or decoded.ndim != 3 or decoded.shape[2] != 3:
            raise ValueError("external crop could not be decoded as a 3-channel image")
        if decoded.dtype != np.uint8 or min(decoded.shape[:2]) < 3:
            raise ValueError("external crop must be a non-empty uint8 image")

        with self._external_classification_lock:
            capture = self._crop_store.save_external(encoded, decoded)
            committed = False
            try:
                classification = self._external_pipeline.classify_capture(
                    capture,
                    request_id=request_id,
                )
                width = int(decoded.shape[1])
                height = int(decoded.shape[0])
                detection = Detection(
                    class_id=-1,
                    label="manual crop",
                    confidence=1.0,
                    box=BoundingBox(0.0, 0.0, float(width), float(height)),
                )
                transform = OverlayTransform.for_frame(
                    width,
                    height,
                    self.settings.preview_width,
                    self.settings.preview_height,
                )
                state = (
                    LockOnState.CAPTURED
                    if classification.result.is_accepted
                    else LockOnState.CHECKING_SHARPNESS
                )
                hint = (
                    "Controller crop classified"
                    if classification.result.is_accepted
                    else "Controller crop needs another view"
                )
                snapshot = ScanSnapshot(
                    sequence=0,
                    timestamp=self._clock(),
                    session_id=f"controller-{classification.request_id}",
                    mode="controller",
                    state=state,
                    hint=hint,
                    transform=transform,
                    source_sequence=None,
                    source_timestamp=None,
                    detections=(detection,),
                    selected_index=0,
                    quality=None,
                    stable_checks=self._lock_config.stable_checks,
                    required_checks=self._lock_config.stable_checks,
                    capture=capture,
                    classification=classification,
                    processing=False,
                    camera_available=self.camera_running,
                    detector_p50_ms=self._detector.metrics.p50_ms if self._detector else 0.0,
                    detector_p95_ms=self._detector.metrics.p95_ms if self._detector else 0.0,
                    controller_lease_id=controller_lease_id,
                )

                def commit() -> None:
                    previous = self._external_capture
                    self._external_capture = capture
                    if previous is not None and previous.path != capture.path:
                        self._crop_store.discard(previous)
                    self.events.publish(snapshot)
                    if on_commit is not None:
                        on_commit(classification)

                if commit_guard is None:
                    commit()
                else:
                    commit_guard(commit)
                committed = True
                return classification
            finally:
                if not committed:
                    self._crop_store.discard(capture)

    # -- background loop -----------------------------------------------------

    def _run(self) -> None:
        if self._controller_mode.is_set():
            self._publish_controller_waiting()
        else:
            self._publish_starting()
        consecutive_failures = 0
        while not self._stop.is_set():
            if self._controller_mode.is_set():
                self._close_resources()
                self._sleep_interruptibly(0.1)
                continue
            if self._pending_fallback is not None:
                self._activate_pending_fallback()
            if self._fallback is not None:
                self._fallback_idle_loop()
                continue
            try:
                self._open_resources()
                consecutive_failures = 0
                self._run_camera_loop()
            except (CameraError, DetectorError) as exc:
                with self._state_lock:
                    self._camera_error = str(exc)
                consecutive_failures += 1
                LOGGER.warning("Scan service camera/detector unavailable: %s", exc)
                self._publish_unavailable(str(exc))
            except Exception as exc:  # pragma: no cover - defensive boundary
                LOGGER.exception("Scan service unexpected failure")
                with self._state_lock:
                    self._camera_error = f"unexpected failure: {exc}"
                consecutive_failures += 1
                self._publish_unavailable(str(exc))
            finally:
                self._close_resources()
            if self._stop.is_set():
                break
            if self._fallback is not None or self._pending_fallback is not None:
                continue
            if consecutive_failures >= self._max_reconnect_attempts:
                self._wait_for_restart()
                if self._fallback is not None:
                    continue
            else:
                self._sleep_interruptibly(self._retry_delay_seconds)
        self._close_resources()

    def _open_resources(self) -> None:
        camera_options = {
            "config": CAMERA_CONFIG,
            "clock": self._clock,
        }
        # Omitting the argument is significant: CameraOwner's constructor
        # supplies the real Picamera2 factory. Passing None here overrides
        # that default and makes the production camera path non-callable.
        if self._camera_factory is not None:
            camera_options["camera_factory"] = self._camera_factory
        camera = CameraOwner(**camera_options)
        camera.open()
        self._camera = camera
        detector = self._ensure_detector()
        if not detector.is_loaded:
            detector.load()
        self._engine = LockOnEngine(self._lock_config, self._crop_store)
        self._pipeline = ClassificationPipeline(self._classifier)
        with self._state_lock:
            self._camera_running = True
            self._detector_loaded = True
            self._camera_error = None
            self._detector_error = None

    def _ensure_detector(self) -> YoloOnnxDetector:
        if self._detector is None:
            if self._detector_override is not None:
                self._detector = self._detector_override
            else:
                try:
                    manifest = ModelManifest.from_file(self.settings.manifest_path)
                    self._detector = YoloOnnxDetector(
                        manifest,
                        confidence_threshold=self.settings.detector_confidence,
                        nms_iou_threshold=self.settings.detector_nms_iou,
                    )
                except DetectorError as exc:
                    self._detector_error = str(exc)
                    raise
        if not self._detector.is_loaded:
            try:
                self._detector.load()
            except DetectorError as exc:
                self._detector_error = str(exc)
                raise
        return self._detector

    def _close_resources(self) -> None:
        camera = self._camera
        self._camera = None
        if camera is not None:
            try:
                camera.close()
            except Exception:  # pragma: no cover - best-effort release
                pass
        self._engine = None
        self._pipeline = None
        with self._state_lock:
            self._camera_running = False
            # A closed or failed camera must not leave a previous frame
            # available to the independent Weed Beta still-image endpoint.
            self._frame = None

    def _run_camera_loop(self) -> None:
        camera = self._camera
        engine = self._engine
        pipeline = self._pipeline
        detector = self._detector
        assert camera is not None and engine is not None and pipeline is not None and detector is not None
        consecutive_drops = 0

        while not self._stop.is_set():
            if self._controller_mode.is_set():
                break
            if self._pending_fallback is not None:
                break
            try:
                captured = camera.read()
            except FrameReadError as exc:
                consecutive_drops += 1
                if consecutive_drops >= self.settings.max_consecutive_drops:
                    raise CameraError(
                        f"camera stopped delivering frames ({consecutive_drops} consecutive drops)"
                    ) from exc
                continue
            consecutive_drops = 0
            if self._controller_mode.is_set():
                break
            self._frame = captured.image
            self._handle_control_flags(engine)

            if self._controller_mode.is_set():
                break
            detections = detector.detect(captured.image)
            preferred = self._preferred_detection(detections)
            update = engine.update(captured.image, detections, preferred=preferred)
            if self._manual_capture_requested:
                with self._state_lock:
                    self._manual_capture_requested = False
                # COCO has no reliable tree/plant coverage beyond its
                # ``potted plant`` class.  A physical tree therefore needs an
                # operator-directed path.  Keep automatic capture strictly
                # detector-driven, but let a manual hotkey capture a nearly
                # full central frame when the current frame has no eligible
                # detector box.
                has_eligible_detection = any(
                    detection.label in self.settings.eligible_labels
                    for detection in detections
                )
                if has_eligible_detection:
                    manual = engine.manual_capture(captured.image, preferred=preferred)
                else:
                    engine.reset()
                    manual = self._manual_frame_capture(captured.image)
                    if manual.detection is not None:
                        detections = [*detections, manual.detection]
                update = manual

            transform = OverlayTransform.for_frame(
                captured.image.shape[1],
                captured.image.shape[0],
                self.settings.preview_width,
                self.settings.preview_height,
            )
            self._publish_preview(captured, transform)

            classification = None
            processing = False
            if update.capture is not None:
                processing = True
                cancellation = CancellationToken()
                with self._state_lock:
                    self._classification_cancellation = cancellation
                self._publish_state(
                    engine,
                    detections,
                    update,
                    transform,
                    captured,
                    processing=True,
                )
                classification = pipeline.classify_capture(
                    update.capture,
                    cancellation=cancellation,
                )
                with self._state_lock:
                    fallback_pending = self._pending_fallback is not None
                    cancelled = (
                        self._cancel_requested
                        or self._reset_requested
                        or cancellation.is_cancelled
                    )
                    cancel_hint = (
                        "Scan cancelled"
                        if self._cancel_requested
                        else "Switching to local image"
                        if fallback_pending
                        else "Ready for another view"
                    )
                    self._cancel_requested = False
                    self._reset_requested = False
                    self._classification_cancellation = None
                if cancelled:
                    engine.reset()
                    self._bump_session()
                    detection = engine.current_detection
                    update = LockOnUpdate(
                        state=engine.state,
                        detection=detection,
                        quality=None,
                        stable_checks=0,
                        required_checks=engine.config.stable_checks,
                        hint=cancel_hint,
                    )
                    classification = None
                if self._controller_mode.is_set():
                    break
                processing = False

            self._publish_state(
                engine,
                detections,
                update,
                transform,
                captured,
                processing=processing,
                classification=classification,
            )

            if classification is not None:
                self._hold_result_until_action(engine)

            if self._fallback is not None or self._pending_fallback is not None:
                self._sleep_interruptibly(0.1)
                break
# -- event and preview publishing ----------------------------------------

    def _publish_starting(self) -> None:
        transform = OverlayTransform.for_frame(
            CAMERA_CONFIG.width,
            CAMERA_CONFIG.height,
            self.settings.preview_width,
            self.settings.preview_height,
        )
        update = LockOnUpdate(
            state=LockOnState.SEARCHING,
            detection=None,
            quality=None,
            stable_checks=0,
            required_checks=self._lock_config.stable_checks,
            hint="Starting camera…",
        )
        snapshot = snapshot_from_update(
            sequence=0,
            timestamp=self._clock(),
            session_id=self._session_id,
            mode="camera",
            transform=transform,
            source_sequence=None,
            source_timestamp=None,
            detections=(),
            selected_index=None,
            update=update,
            processing=False,
            camera_available=False,
            detector_p50_ms=0.0,
            detector_p95_ms=0.0,
        )
        self.events.publish(snapshot)

    def _publish_unavailable(self, message: str) -> None:
        transform = OverlayTransform.for_frame(
            CAMERA_CONFIG.width,
            CAMERA_CONFIG.height,
            self.settings.preview_width,
            self.settings.preview_height,
        )
        update = LockOnUpdate(
            state=LockOnState.SEARCHING,
            detection=None,
            quality=None,
            stable_checks=0,
            required_checks=self._lock_config.stable_checks,
            hint="Camera unavailable — use a local image",
        )
        snapshot = snapshot_from_update(
            sequence=0,
            timestamp=self._clock(),
            session_id=self._session_id,
            mode="camera",
            transform=transform,
            source_sequence=None,
            source_timestamp=None,
            detections=(),
            selected_index=None,
            update=update,
            processing=False,
            camera_available=False,
            detector_p50_ms=0.0,
            detector_p95_ms=0.0,
            error=message,
        )
        self.events.publish(snapshot)

    def _publish_controller_waiting(self) -> None:
        snapshot = ScanSnapshot(
            sequence=0,
            timestamp=self._clock(),
            session_id=f"controller-{int(self._clock() * 1000)}",
            mode="controller",
            state=LockOnState.SEARCHING,
            hint="Waiting for a crop from the paired browser",
            transform=None,
            source_sequence=None,
            source_timestamp=None,
            detections=(),
            selected_index=None,
            quality=None,
            stable_checks=0,
            required_checks=self._lock_config.stable_checks,
            capture=None,
            classification=None,
            processing=False,
            camera_available=False,
            detector_p50_ms=0.0,
            detector_p95_ms=0.0,
        )
        self.events.publish(snapshot)

    def _publish_preview(self, captured, transform: OverlayTransform) -> None:
        frame = self._frame
        if frame is None:
            return
        encoded = encode_jpeg(
            letterbox_frame(captured.image, transform),
            self.settings.preview_jpeg_quality,
        )
        self.preview_buffer.put(
            PreviewFrame(
                sequence=self._next_preview_sequence(),
                captured_at=captured.captured_at,
                source_sequence=captured.sequence,
                transform=transform,
                jpeg_bytes=encoded,
            )
        )

    def _publish_state(
        self,
        engine: LockOnEngine,
        detections,
        update: LockOnUpdate,
        transform: OverlayTransform,
        captured,
        *,
        processing: bool,
        classification=None,
    ) -> None:
        detector = self._detector
        p50 = detector.metrics.p50_ms if detector is not None else 0.0
        p95 = detector.metrics.p95_ms if detector is not None else 0.0
        snapshot = snapshot_from_update(
            sequence=0,
            timestamp=self._clock(),
            session_id=self._session_id,
            mode="camera",
            transform=transform,
            source_sequence=captured.sequence,
            source_timestamp=captured.captured_at,
            detections=tuple(detections),
            selected_index=_detection_index(tuple(detections), update.detection or engine.current_detection),
            update=update,
            processing=processing,
            camera_available=True,
            detector_p50_ms=p50,
            detector_p95_ms=p95,
            classification=classification,
        )
        self.events.publish(snapshot)

    def _publish_fallback(
        self,
        *,
        processing: bool,
        hint: str,
        update: LockOnUpdate | None = None,
        classification=None,
    ) -> None:
        fallback = self._fallback
        if fallback is None:
            return
        update = update or LockOnUpdate(
            state=LockOnState.SEARCHING,
            detection=None,
            quality=None,
            stable_checks=0,
            required_checks=self._lock_config.stable_checks,
            hint=hint,
        )
        selected_index = self._selected_index if self._selected_index is not None else 0
        if selected_index >= len(fallback.detections):
            selected_index = 0
        if fallback.detections:
            selected = fallback.detections[selected_index]
            update = LockOnUpdate(
                state=update.state,
                detection=selected,
                quality=update.quality,
                stable_checks=update.stable_checks,
                required_checks=update.required_checks,
                hint=update.hint,
                capture=update.capture,
            )
        detector = self._detector
        p50 = detector.metrics.p50_ms if detector is not None else 0.0
        p95 = detector.metrics.p95_ms if detector is not None else 0.0
        snapshot = snapshot_from_update(
            sequence=0,
            timestamp=self._clock(),
            session_id=self._session_id,
            mode="fallback",
            transform=fallback.transform,
            source_sequence=self._fallback_sequence,
            source_timestamp=fallback.created_at,
            detections=tuple(fallback.detections),
            selected_index=selected_index if fallback.detections else None,
            update=update,
            processing=processing,
            camera_available=False,
            detector_p50_ms=p50,
            detector_p95_ms=p95,
            classification=classification,
        )
        self.events.publish(snapshot)

    def _publish_fallback_preview(self, fallback: FallbackImage) -> None:
        encoded = encode_jpeg(
            letterbox_frame(fallback.image, fallback.transform),
            self.settings.preview_jpeg_quality,
        )
        self._fallback_sequence += 1
        self.preview_buffer.put(
            PreviewFrame(
                sequence=self._next_preview_sequence(),
                captured_at=fallback.created_at,
                source_sequence=self._fallback_sequence,
                transform=fallback.transform,
                jpeg_bytes=encoded,
            )
        )

    def _activate_pending_fallback(self) -> None:
        with self._state_lock:
            pending = self._pending_fallback
            self._pending_fallback = None
        if pending is None:
            return
        image, name = pending
        height, width = image.shape[:2]
        detections: list[Detection] = []
        try:
            detector = self._ensure_detector()
            detections = [
                detection
                for detection in detector.detect(image)
                if detection.label in self.settings.eligible_labels
            ]
            with self._state_lock:
                self._detector_loaded = True
                self._detector_error = None
        except DetectorError as exc:
            LOGGER.warning("Detector unavailable for local image; using manual image selection: %s", exc)
            with self._state_lock:
                self._detector_loaded = False
                self._detector_error = str(exc)

        if not detections:
            inset_x = max(1.0, width * 0.02)
            inset_y = max(1.0, height * 0.02)
            detections = [
                Detection(
                    class_id=-1,
                    label="manual image",
                    confidence=1.0,
                    box=BoundingBox(inset_x, inset_y, width - inset_x, height - inset_y),
                )
            ]
        transform = OverlayTransform.for_frame(
            width,
            height,
            self.settings.preview_width,
            self.settings.preview_height,
        )
        fallback = FallbackImage(
            image=image,
            name=name,
            transform=transform,
            detections=detections,
            created_at=self._clock(),
        )
        with self._state_lock:
            self._fallback = fallback
            self._selected_index = 0
            self._camera_error = None
        self._pipeline = ClassificationPipeline(self._classifier)
        self._publish_fallback_preview(fallback)
        self._publish_fallback(processing=False, hint=f"Local image selected: {name}")
# -- fallback image session ----------------------------------------------

    def _fallback_idle_loop(self) -> None:
        while not self._stop.is_set():
            if self._fallback is None:
                return
            if self._reset_requested or self._cancel_requested:
                with self._state_lock:
                    cancelled = self._cancel_requested
                    self._reset_requested = False
                    self._cancel_requested = False
                self._bump_session()
                self._publish_fallback(
                    processing=False,
                    hint="Scan cancelled" if cancelled else "Ready for another view",
                )
                continue
            if self._fallback_capture_requested:
                with self._state_lock:
                    self._fallback_capture_requested = False
                    index = self._fallback_capture_index
                self._run_fallback_capture(index)
            if self._fallback_clear_requested:
                with self._state_lock:
                    self._fallback_clear_requested = False
                    self._fallback = None
                self._bump_session()
                return
            if self._restart_requested:
                with self._state_lock:
                    self._restart_requested = False
                    self._fallback = None
                self._bump_session()
                return
            self._sleep_interruptibly(0.1)

    def _run_fallback_capture(self, index: int) -> None:
        fallback = self._fallback
        if fallback is None:
            return
        if index < 0 or index >= len(fallback.detections):
            self._publish_fallback(
                processing=False,
                hint="No eligible target in the local image",
            )
            return
        selected = fallback.detections[index]
        frame = fallback.image
        height, width = frame.shape[:2]
        crop = _crop_region(frame, selected.box)
        quality = evaluate_crop(crop, selected.box, width, height, self._quality_config)
        if not quality.ready:
            self._publish_fallback(
                processing=False,
                hint=quality.hint,
                update=LockOnUpdate(
                    state=LockOnState.SEARCHING,
                    detection=selected,
                    quality=quality,
                    stable_checks=0,
                    required_checks=self._lock_config.stable_checks,
                    hint=quality.hint,
                ),
            )
            return
        self._fallback_sequence += 1
        capture = self._crop_store.save(frame, selected.box, manual=True)
        pipeline = self._pipeline
        if pipeline is None:
            pipeline = ClassificationPipeline(self._classifier)
            self._pipeline = pipeline
        cancellation = CancellationToken()
        with self._state_lock:
            self._classification_cancellation = cancellation
        self._publish_fallback(
            processing=True,
            hint="Processing plant…",
            update=LockOnUpdate(
                state=LockOnState.CAPTURED,
                detection=selected,
                quality=quality,
                stable_checks=self._lock_config.stable_checks,
                required_checks=self._lock_config.stable_checks,
                hint="Processing plant…",
                capture=capture,
            ),
        )
        classification = pipeline.classify_capture(capture, cancellation=cancellation)
        with self._state_lock:
            cancelled = (
                self._cancel_requested
                or self._reset_requested
                or cancellation.is_cancelled
            )
            cancel_hint = "Scan cancelled" if self._cancel_requested else "Ready for another view"
            self._cancel_requested = False
            self._reset_requested = False
            self._classification_cancellation = None
        if cancelled:
            self._publish_fallback(processing=False, hint=cancel_hint)
            return
        self._publish_fallback(
            processing=False,
            hint="Local crop classified",
            update=LockOnUpdate(
                state=LockOnState.CAPTURED,
                detection=selected,
                quality=quality,
                stable_checks=self._lock_config.stable_checks,
                required_checks=self._lock_config.stable_checks,
                hint="Local crop captured",
                capture=capture,
            ),
            classification=classification,
        )

    def _manual_frame_capture(self, frame: np.ndarray) -> LockOnUpdate:
        """Build an operator-only central ROI for undetected plants/trees.

        The generic detector is intentionally not taught that every green
        object is a plant.  When the operator explicitly requests capture and
        no eligible box exists, this path preserves a large central view and
        sends only that crop through the normal quality/classification
        pipeline.  It never runs from :meth:`LockOnEngine.update`, so it
        cannot trigger automatic capture.
        """

        height, width = frame.shape[:2]
        inset_x = max(1.0, width * MANUAL_FRAME_INSET_RATIO)
        inset_y = max(1.0, height * MANUAL_FRAME_INSET_RATIO)
        box = BoundingBox(
            inset_x,
            inset_y,
            max(inset_x + 1.0, width - inset_x),
            max(inset_y + 1.0, height - inset_y),
        )
        detection = Detection(
            class_id=MANUAL_FRAME_CLASS_ID,
            label=MANUAL_FRAME_LABEL,
            confidence=1.0,
            box=box,
        )
        crop = _crop_region(frame, box)
        quality = evaluate_crop(crop, box, width, height, self._quality_config)
        if not quality.ready:
            return LockOnUpdate(
                state=LockOnState.CHECKING_SHARPNESS,
                detection=detection,
                quality=quality,
                stable_checks=0,
                required_checks=self._lock_config.stable_checks,
                hint=f"Manual view: {quality.hint}",
            )

        capture = self._crop_store.save(frame, box, manual=True)
        return LockOnUpdate(
            state=LockOnState.CAPTURED,
            detection=detection,
            quality=quality,
            stable_checks=self._lock_config.stable_checks,
            required_checks=self._lock_config.stable_checks,
            hint="Manual central view captured",
            capture=capture,
        )

    # -- small control helpers ----------------------------------------------

    def _handle_control_flags(self, engine: LockOnEngine) -> None:
        if self._reset_requested:
            with self._state_lock:
                self._reset_requested = False
                self._selected_index = None
            engine.reset()
            self._bump_session()
        if self._cancel_requested:
            with self._state_lock:
                self._cancel_requested = False
                self._selected_index = None
            engine.reset()
            self._bump_session()

    def _hold_result_until_action(self, engine: LockOnEngine) -> None:
        """Keep a terminal result authoritative until the operator acts."""

        while not self._stop.is_set():
            if self._controller_mode.is_set():
                return
            with self._state_lock:
                reset = self._reset_requested
                cancelled = self._cancel_requested
                fallback_pending = self._pending_fallback is not None
                if reset or cancelled:
                    self._reset_requested = False
                    self._cancel_requested = False
                    self._selected_index = None
            if reset or cancelled:
                engine.reset()
                self._bump_session()
                return
            if fallback_pending:
                return
            self._sleep_interruptibly(0.05)

    def _next_preview_sequence(self) -> int:
        with self._state_lock:
            self._preview_sequence += 1
            return self._preview_sequence

    def _preferred_detection(self, detections) -> Detection | None:
        if self._selected_index is None:
            return None
        if 0 <= self._selected_index < len(detections):
            candidate = detections[self._selected_index]
            if candidate.label in self.settings.eligible_labels:
                return candidate
        with self._state_lock:
            self._selected_index = None
        return None

    def _bump_session(self) -> None:
        with self._state_lock:
            self._session_id = f"scan-{int(self._clock() * 1000)}"

    def _wait_for_restart(self) -> None:
        while (
            not self._stop.is_set()
            and not self._restart_requested
            and self._fallback is None
            and self._pending_fallback is None
        ):
            self._sleep_interruptibly(0.2)
        with self._state_lock:
            self._restart_requested = False

    def _sleep_interruptibly(self, seconds: float) -> None:
        self._stop.wait(timeout=seconds)
