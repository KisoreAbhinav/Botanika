"""Small, licensed visual embedding runtime for campus few-shot labels.

The Pi does not have a useful training accelerator, and five photographs per
plant are not enough to train a new convolutional network from scratch.  This
module therefore uses the official ONNX Model Zoo MobileNetV2 ImageNet model
as a frozen visual encoder. A reproducible graph export exposes its
1,280-dimensional penultimate tensor (the classifier-input feature), which is
L2-normalised before prototype/nearest-neighbour search.

The model is intentionally loaded from a machine-local path.  Botanika never
downloads a weight at application start.  The model manifest and SHA-256 are
checked before creating an ONNX Runtime session.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np


MOBILENETV2_MODEL_ID = "onnx-model-zoo.mobilenetv2-1.0-penultimate"
MOBILENETV2_VERSION = "mobilenetv2-1.0-fp32-penultimate-472"
MOBILENETV2_SOURCE = (
    "https://github.com/onnx/models/raw/main/validated/vision/classification/"
    "mobilenet/model/mobilenetv2-10.onnx"
)
MOBILENETV2_MODEL_CARD = (
    "https://github.com/onnx/models/blob/main/validated/vision/classification/"
    "mobilenet/README.md"
)
MOBILENETV2_LICENSE = "Apache-2.0"
MOBILENETV2_LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0"
# SHA-256 of the derived ONNX file with graph output ``472``. The original
# official download SHA is recorded in the tracked model manifest and in the
# preparation tool; the derived file contains the same weights/operators.
MOBILENETV2_SHA256 = "10ddb16ca5df7d3fde89ec18aa99f768a75c16e700e680d03f25d1b3b8b720c4"
INPUT_WIDTH = 224
INPUT_HEIGHT = 224
INPUT_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
INPUT_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)

# The artifact records a model ID and checksum, rather than relying on a
# filename.  Adding a future plant-trained encoder is an explicit registry
# change: its loader, source/license contract, and checksum must be reviewed
# before an enrollment artifact can use it.
SUPPORTED_EMBEDDING_MODELS = {
    MOBILENETV2_MODEL_ID: {
        "version": MOBILENETV2_VERSION,
        "sha256": MOBILENETV2_SHA256,
    },
}


class EmbeddingModelError(RuntimeError):
    """Raised when the frozen embedding runtime cannot be trusted."""


@dataclass(frozen=True, slots=True)
class EmbeddingModelMetadata:
    """Auditable description of the downloaded encoder and preprocessing."""

    model_id: str
    version: str
    runtime: str
    artifact_path: Path
    artifact_sha256: str
    embedding_dimensions: int
    input_width: int
    input_height: int
    source: str
    model_card: str
    license: str
    license_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "runtime": self.runtime,
            "artifact_path": str(self.artifact_path),
            "artifact_sha256": self.artifact_sha256,
            "embedding_dimensions": self.embedding_dimensions,
            "input": {
                "width": self.input_width,
                "height": self.input_height,
                "channels": 3,
                "color_order": "RGB",
                "normalization": {
                    "scale": "uint8-to-0-1",
                    "mean": [float(value) for value in INPUT_MEAN],
                    "std": [float(value) for value in INPUT_STD],
                },
            },
            "source": self.source,
            "model_card": self.model_card,
            "license": self.license,
            "license_url": self.license_url,
        }


class MobileNetV2Embedder:
    """CPU ONNX Runtime wrapper returning deterministic unit vectors.

    The ONNX Model Zoo publishes the classification head rather than a
    feature-export graph. Botanika's one-time preparation step exposes the
    classifier-input tensor (node ``472``) without changing any weights. This
    is a stronger retrieval representation than final class scores while the
    metadata still makes clear that it is not a plant-specific foundation
    model.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        expected_sha256: str = MOBILENETV2_SHA256,
        intra_op_num_threads: int = 2,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_file():
            raise EmbeddingModelError(f"embedding model not found: {self.model_path}")
        actual = sha256_file(self.model_path)
        if expected_sha256 and actual != expected_sha256.lower():
            raise EmbeddingModelError(
                f"embedding model checksum mismatch: expected {expected_sha256}, got {actual}"
            )
        try:
            import onnxruntime as ort
        except Exception as exc:  # pragma: no cover - environment dependent
            raise EmbeddingModelError(f"onnxruntime is unavailable: {exc}") from exc

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(intra_op_num_threads))
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        try:
            self._session = ort.InferenceSession(
                str(self.model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:  # pragma: no cover - runtime/model dependent
            raise EmbeddingModelError(f"could not load embedding model: {exc}") from exc
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise EmbeddingModelError("embedding model must expose one input and one output")
        input_shape = list(inputs[0].shape)
        if len(input_shape) != 4 or input_shape[1:] != [3, INPUT_HEIGHT, INPUT_WIDTH]:
            raise EmbeddingModelError(f"unexpected MobileNetV2 input shape: {input_shape!r}")
        output_shape = list(outputs[0].shape)
        if len(output_shape) != 2 or not isinstance(output_shape[1], int) or output_shape[1] <= 0:
            raise EmbeddingModelError(f"unexpected MobileNetV2 output shape: {output_shape!r}")
        self._input_name = str(inputs[0].name)
        self._output_name = str(outputs[0].name)
        self._embedding_dimensions = int(output_shape[1])
        self._metadata = EmbeddingModelMetadata(
            model_id=MOBILENETV2_MODEL_ID,
            version=MOBILENETV2_VERSION,
            runtime=f"onnxruntime-{getattr(ort, '__version__', 'unknown')}",
            artifact_path=self.model_path,
            artifact_sha256=actual,
            embedding_dimensions=self._embedding_dimensions,
            input_width=INPUT_WIDTH,
            input_height=INPUT_HEIGHT,
            source=MOBILENETV2_SOURCE,
            model_card=MOBILENETV2_MODEL_CARD,
            license=MOBILENETV2_LICENSE,
            license_url=MOBILENETV2_LICENSE_URL,
        )

    @property
    def metadata(self) -> EmbeddingModelMetadata:
        return self._metadata

    @property
    def dimensions(self) -> int:
        return self._embedding_dimensions

    def embed(self, image: np.ndarray) -> np.ndarray:
        """Embed one BGR image with the Model Zoo preprocessing contract."""

        batch = preprocess_image(image)
        try:
            output = self._session.run([self._output_name], {self._input_name: batch})[0]
        except Exception as exc:  # pragma: no cover - runtime dependent
            raise EmbeddingModelError(f"embedding inference failed: {exc}") from exc
        vector = np.asarray(output, dtype=np.float32).reshape(-1)
        if vector.size != self._embedding_dimensions or not np.all(np.isfinite(vector)):
            raise EmbeddingModelError("embedding model returned a malformed vector")
        return _unit_vector(vector)

    def embed_views(self, image: np.ndarray) -> np.ndarray:
        """Average original and mirrored views for a modest robustness gain."""

        original = self.embed(image)
        mirrored = self.embed(np.ascontiguousarray(image[:, ::-1]))
        return _unit_vector((original + mirrored) / 2.0)


def load_embedding_model(model_path: Path, metadata: Mapping[str, Any]) -> MobileNetV2Embedder:
    """Load the reviewed encoder named by an enrollment artifact.

    Keeping this lookup separate from the campus classifier makes the model
    boundary replaceable while still rejecting an unreviewed model ID or a
    checksum that does not belong to that ID.  A future encoder can register a
    compatible loader here without changing artifact scoring or storage.
    """

    model_id = str(metadata.get("model_id") or "").strip()
    specification = SUPPORTED_EMBEDDING_MODELS.get(model_id)
    if specification is None:
        raise EmbeddingModelError(f"unsupported embedding model ID: {model_id or '<missing>'}")
    expected_sha = str(metadata.get("artifact_sha256") or "").strip().lower()
    if expected_sha != str(specification["sha256"]):
        raise EmbeddingModelError(
            f"embedding checksum is not approved for {model_id}: {expected_sha or '<missing>'}"
        )
    expected_version = str(specification["version"])
    if str(metadata.get("version") or "") != expected_version:
        raise EmbeddingModelError(
            f"embedding version is not approved for {model_id}: {metadata.get('version')!r}"
        )
    if model_id == MOBILENETV2_MODEL_ID:
        return MobileNetV2Embedder(Path(model_path), expected_sha256=expected_sha)
    # The registry check above intentionally leaves a clear extension point;
    # keep this defensive branch so adding metadata alone cannot load a model.
    raise EmbeddingModelError(f"no loader registered for embedding model ID: {model_id}")


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """Letterbox-free center crop matching the Model Zoo ImageNet recipe."""

    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise EmbeddingModelError("embedding input must be a 3-channel BGR image")
    if image.dtype != np.uint8 or min(image.shape[:2]) < 3:
        raise EmbeddingModelError("embedding input must be a non-empty uint8 image")
    height, width = image.shape[:2]
    scale = 256.0 / min(height, width)
    resized_width = max(INPUT_WIDTH, int(round(width * scale)))
    resized_height = max(INPUT_HEIGHT, int(round(height * scale)))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    left = max(0, (resized_width - INPUT_WIDTH) // 2)
    top = max(0, (resized_height - INPUT_HEIGHT) // 2)
    crop = resized[top : top + INPUT_HEIGHT, left : left + INPUT_WIDTH]
    if crop.shape[:2] != (INPUT_HEIGHT, INPUT_WIDTH):
        crop = cv2.resize(crop, (INPUT_WIDTH, INPUT_HEIGHT), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - INPUT_MEAN) / INPUT_STD
    return np.ascontiguousarray(np.transpose(rgb, (2, 0, 1))[None, ...], dtype=np.float32)


def _unit_vector(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1e-8:
        raise EmbeddingModelError("embedding vector has zero or non-finite norm")
    return np.asarray(vector / norm, dtype=np.float32)


def sha256_file(path: Path) -> str:
    """Hash a model or source image in bounded chunks."""

    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EmbeddingModelError(f"could not hash {path}: {exc}") from exc
    return digest.hexdigest()


def canonical_json(value: Mapping[str, Any]) -> bytes:
    """Canonical JSON used for immutable enrollment artifact checksums."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
