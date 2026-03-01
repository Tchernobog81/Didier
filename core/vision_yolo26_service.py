"""Pure YOLO26 helpers for raw 6-head Hailo outputs."""

from __future__ import annotations

import copy
from typing import Any
from typing import Callable

import numpy as np


def normalize_spatial_head(tensor: Any) -> np.ndarray | None:
    try:
        arr = np.asarray(tensor)
    except Exception:
        return None
    while arr.ndim > 3 and int(arr.shape[0]) == 1:
        arr = arr[0]
    if arr.ndim != 3:
        return None
    if int(arr.shape[-1]) in {4, 80}:
        return np.asarray(arr, dtype=np.float32)
    if int(arr.shape[0]) in {4, 80}:
        return np.asarray(np.moveaxis(arr, 0, -1), dtype=np.float32)
    return None


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def apply_class_aware_nms(
    detections: list[dict[str, Any]],
    *,
    apply_nms: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if len(detections) <= 1:
        return detections
    grouped: dict[int | None, list[dict[str, Any]]] = {}
    for det in detections:
        grouped.setdefault(det.get("class_id"), []).append(det)
    filtered: list[dict[str, Any]] = []
    for group in grouped.values():
        filtered.extend(apply_nms(group))
    filtered.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
    return filtered


def decode_yolo26_head_pairs(
    outputs: Any,
    *,
    frame_w: int | None,
    frame_h: int | None,
    input_shape: tuple[int, int, int] | None,
    preprocess_meta: dict[str, Any] | None,
    score_threshold: float,
    max_detections: int,
    apply_nms: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    map_box_to_frame: Callable[..., list[int] | None],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not isinstance(outputs, dict) or not frame_w or not frame_h:
        return None, None

    heads: dict[tuple[int, int], dict[str, tuple[str, np.ndarray]]] = {}
    for key, tensor in outputs.items():
        arr = normalize_spatial_head(tensor)
        if arr is None:
            continue
        grid_h, grid_w, channels = (int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2]))
        slot = heads.setdefault((grid_h, grid_w), {})
        if channels == 4 and "box" not in slot:
            slot["box"] = (str(key), arr)
        elif channels > 4 and "cls" not in slot:
            slot["cls"] = (str(key), arr)

    paired = [
        ((grid_h, grid_w), slot["box"], slot["cls"])
        for (grid_h, grid_w), slot in heads.items()
        if "box" in slot and "cls" in slot
    ]
    if not paired:
        return None, None

    model_h = int((input_shape or (frame_h, frame_w, 3))[0] or frame_h)
    model_w = int((input_shape or (frame_h, frame_w, 3))[1] or frame_w)
    head_limit = max(128, int(max_detections) * 8)

    detections: list[dict[str, Any]] = []
    head_debug: list[dict[str, Any]] = []
    for (grid_h, grid_w), (box_name, box_arr), (cls_name, cls_arr) in sorted(
        paired,
        key=lambda item: item[0][0],
        reverse=True,
    ):
        stride_x = float(model_w) / float(max(1, grid_w))
        stride_y = float(model_h) / float(max(1, grid_h))
        boxes = np.asarray(box_arr, dtype=np.float32).reshape(-1, 4)
        logits = np.asarray(cls_arr, dtype=np.float32).reshape(-1, int(cls_arr.shape[-1]))
        class_ids = np.argmax(logits, axis=1).astype(np.int32)
        raw_scores = logits[np.arange(int(logits.shape[0])), class_ids]
        if float(np.min(logits)) < 0.0 or float(np.max(logits)) > 1.0:
            scores = sigmoid(raw_scores)
            score_mode = "sigmoid_logits"
        else:
            scores = np.clip(raw_scores, 0.0, 1.0)
            score_mode = "probabilities"

        top_preview: list[dict[str, Any]] = []
        preview_count = min(3, int(scores.size))
        if preview_count > 0:
            preview_start = max(0, int(scores.size) - preview_count)
            preview_idx = np.argpartition(scores, preview_start)[preview_start:]
            preview_idx = preview_idx[np.argsort(scores[preview_idx])[::-1]]
            for preview in preview_idx:
                top_preview.append(
                    {
                        "grid_xy": [
                            int(preview % max(1, grid_w)),
                            int(preview // max(1, grid_w)),
                        ],
                        "class_id": int(class_ids[preview]),
                        "score": round(float(scores[preview]), 4),
                        "box_raw": [
                            round(float(value), 4)
                            for value in np.asarray(boxes[preview]).reshape(-1)[:4]
                        ],
                    }
                )

        keep_idx = np.flatnonzero(scores >= float(score_threshold))
        kept_before_cap = int(keep_idx.size)
        if keep_idx.size > head_limit:
            ranked = scores[keep_idx]
            top_local = np.argpartition(ranked, -head_limit)[-head_limit:]
            keep_idx = keep_idx[top_local]

        head_debug.append(
            {
                "grid": [grid_w, grid_h],
                "stride": [round(stride_x, 3), round(stride_y, 3)],
                "box_head": box_name,
                "cls_head": cls_name,
                "score_mode": score_mode,
                "candidates": int(logits.shape[0]),
                "above_threshold": kept_before_cap,
                "kept_for_decode": int(keep_idx.size),
                "box_range": [
                    round(float(np.min(boxes)), 4),
                    round(float(np.max(boxes)), 4),
                ],
                "score_range": [
                    round(float(np.min(scores)), 4),
                    round(float(np.max(scores)), 4),
                ],
                "top_candidates": top_preview,
            }
        )
        if keep_idx.size == 0:
            continue

        grid_y = (keep_idx // max(1, grid_w)).astype(np.float32)
        grid_x = (keep_idx % max(1, grid_w)).astype(np.float32)
        ltrb = np.maximum(boxes[keep_idx], 0.0)

        anchor_x = grid_x + 0.5
        anchor_y = grid_y + 0.5
        x1 = (anchor_x - ltrb[:, 0]) * stride_x
        y1 = (anchor_y - ltrb[:, 1]) * stride_y
        x2 = (anchor_x + ltrb[:, 2]) * stride_x
        y2 = (anchor_y + ltrb[:, 3]) * stride_y

        x1 = np.clip(x1, 0.0, float(model_w - 1))
        y1 = np.clip(y1, 0.0, float(model_h - 1))
        x2 = np.clip(x2, 0.0, float(model_w))
        y2 = np.clip(y2, 0.0, float(model_h))

        for pos, idx in enumerate(keep_idx):
            bbox = map_box_to_frame(
                x1=float(x1[pos]),
                y1=float(y1[pos]),
                x2=float(x2[pos]),
                y2=float(y2[pos]),
                frame_w=int(frame_w),
                frame_h=int(frame_h),
                preprocess_meta=preprocess_meta,
                input_shape=input_shape,
            )
            if not bbox:
                continue
            class_id = int(class_ids[idx])
            detections.append(
                {
                    "label": f"class_{class_id}",
                    "confidence": float(scores[idx]),
                    "bbox": bbox,
                    "class_id": class_id,
                }
            )

    filtered = apply_class_aware_nms(detections, apply_nms=apply_nms)
    debug = {
        "decode_path": "yolo26_raw_head_pairs",
        "score_threshold": round(float(score_threshold), 4),
        "head_pairs": head_debug,
        "raw_detections": int(len(detections)),
        "nms_kept": int(len(filtered)),
        "nms_mode": "class_aware",
    }
    return filtered, debug


def decorate_debug_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    class_name_for_id: Callable[[Any], str | None],
) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return snapshot
    payload = copy.deepcopy(snapshot)
    head_pairs = payload.get("head_pairs", [])
    if not isinstance(head_pairs, list):
        return payload
    for head in head_pairs:
        if not isinstance(head, dict):
            continue
        candidates = head.get("top_candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            class_name = class_name_for_id(candidate.get("class_id"))
            if class_name:
                candidate["class_name"] = class_name
    return payload


def build_object_hints(
    snapshot: dict[str, Any] | None,
    *,
    class_name_for_id: Callable[[Any], str | None],
    min_score: float = 0.01,
    max_items: int = 3,
) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    head_pairs = snapshot.get("head_pairs", [])
    if not isinstance(head_pairs, list):
        return None
    try:
        score_threshold = float(snapshot.get("score_threshold"))
    except Exception:
        score_threshold = None
    best_by_key: dict[tuple[int | None, str], dict[str, Any]] = {}
    for head in head_pairs:
        if not isinstance(head, dict):
            continue
        grid = head.get("grid")
        top_candidates = head.get("top_candidates", [])
        if not isinstance(top_candidates, list):
            continue
        for candidate in top_candidates:
            if not isinstance(candidate, dict):
                continue
            try:
                score = float(candidate.get("score"))
            except Exception:
                continue
            if score < float(min_score):
                continue
            class_name = class_name_for_id(candidate.get("class_id"))
            if not class_name:
                class_name = str(candidate.get("class_name") or "").strip() or None
            key = (candidate.get("class_id"), class_name or "")
            threshold_gap = None
            if score_threshold is not None:
                threshold_gap = round(max(0.0, score_threshold - score), 4)
            hint = {
                "class_id": candidate.get("class_id"),
                "label": class_name or "objet",
                "score": round(score, 4),
                "confirmed": bool(score_threshold is not None and score >= score_threshold),
                "threshold_gap": threshold_gap,
            }
            if isinstance(grid, list) and len(grid) >= 2:
                hint["grid"] = [int(grid[0]), int(grid[1])]
            current = best_by_key.get(key)
            if current is None or float(hint.get("score", 0.0)) > float(
                current.get("score", 0.0)
            ):
                best_by_key[key] = hint
    hints = list(best_by_key.values())
    if not hints:
        return None
    hints.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    best = hints[0]
    return {
        "best_label": best["label"],
        "best_score": best["score"],
        "score_threshold": round(score_threshold, 4)
        if score_threshold is not None
        else None,
        "under_threshold": bool(
            score_threshold is not None and float(best["score"]) < score_threshold
        ),
        "threshold_gap": best.get("threshold_gap"),
        "top_labels": hints[: max(1, int(max_items))],
    }
