#!/usr/bin/env python3
"""Expose MobileNetV2's penultimate feature without changing its weights.

This one-time preparation step is intentionally separate from the Pi runtime:
the running application needs only ``onnxruntime``.  It takes the official
ONNX Model Zoo MobileNetV2 model and replaces the final graph output with node
``472`` (the 1,280-dimensional classifier-input tensor), then checks the ONNX
graph before writing the derived artifact.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        import onnx
        from onnx import TensorProto, helper
    except Exception as exc:
        print(f"onnx graph tooling is required only for preparation: {exc}", file=sys.stderr)
        return 2
    model = onnx.load(str(args.source), load_external_data=False)
    if not any(node.output and node.output[0] == "472" for node in model.graph.node):
        print("the expected MobileNetV2 classifier-input node 472 was not found", file=sys.stderr)
        return 2
    del model.graph.output[:]
    model.graph.output.add().CopyFrom(
        helper.make_tensor_value_info("472", TensorProto.FLOAT, ["batch_size", 1280])
    )
    try:
        onnx.checker.check_model(model)
    except Exception as exc:
        print(f"derived ONNX graph failed validation: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

