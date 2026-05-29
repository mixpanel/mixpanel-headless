"""tslearn adapter for ReplayBundle.cluster (044, US4/T080).

Clusters session-replay sequences using ``tslearn``'s DTW-based
``TimeSeriesKMeans``. ``tslearn`` is an optional dependency behind the
``[replay-ml]`` extra; this module's only import side-effect is
``import tslearn`` inside :func:`cluster_bundle`.

The adapter projects each replay's action stream (or page stream) into
an integer sequence keyed by a sorted vocabulary, then runs DTW k-means
over the resulting variable-length series. Each output bundle replay
gains a ``cluster_label`` attribute via :func:`dataclasses.replace`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from mixpanel_headless.types import ReplayBundle


def cluster_bundle(
    bundle: ReplayBundle,
    n: int,
    *,
    features: Literal["actions", "pages"] = "actions",
    seed: int | None = None,
) -> ReplayBundle:
    """Cluster the bundle's replays via DTW k-means.

    Args:
        bundle: The bundle to cluster.
        n: Number of clusters.
        features: ``"actions"`` clusters on action-name sequences;
            ``"pages"`` clusters on URL sequences.
        seed: Optional seed for reproducible cluster assignments.

    Returns:
        A new :class:`ReplayBundle` whose replays carry a
        ``cluster_label`` attribute in ``{0, 1, …, n-1}``.

    Raises:
        ImportError: ``tslearn`` is not installed.
    """
    import numpy as np
    from tslearn.clustering import TimeSeriesKMeans

    # Import here to dodge the types ↔ ml_adapter circular at module load.
    from mixpanel_headless.types import ReplayBundle as _Bundle

    if not bundle.replays:
        return _Bundle(
            replays=[],
            computed_at=bundle.computed_at,
            project_id=bundle.project_id,
        )

    sequences: list[list[str]]
    if features == "actions":
        sequences = [[str(a.action) for a in r.actions] for r in bundle.replays]
    else:
        sequences = [
            [a.url or "" for a in r.actions if a.action == "navigate"]
            for r in bundle.replays
        ]

    # Build a shared vocabulary so the integer projections are
    # comparable across replays.
    vocab: dict[str, int] = {}
    for seq in sequences:
        for token in seq:
            if token not in vocab:
                vocab[token] = len(vocab)

    # A replay can legitimately have an empty feature sequence — e.g. a
    # clicks-only session under features="pages" (no navigations), or a replay
    # the analyzer produced no actions for. tslearn's resampler calls
    # numpy.interp, which raises "array of sample points is empty" on a
    # zero-length series, so represent an empty sequence with a single sentinel
    # token (distinct from any vocab index, which start at 0). Such replays
    # then cluster together by their emptiness rather than crashing the run.
    _empty_sentinel = -1.0
    integer_series = [
        np.array(
            [float(vocab[token]) for token in seq] or [_empty_sentinel],
            dtype=float,
        ).reshape(-1, 1)
        for seq in sequences
    ]

    # tslearn expects a 3-D numpy array of shape (n_series, max_len, 1);
    # use its padding utility.
    from tslearn.utils import to_time_series_dataset

    X = to_time_series_dataset(integer_series)
    model = TimeSeriesKMeans(n_clusters=n, metric="dtw", random_state=seed)
    labels = model.fit_predict(X)

    # Attach cluster_label as a per-replay attribute. Since Replay is a
    # frozen dataclass, we use object.__setattr__ to add the attribute
    # without violating the frozen invariant for the originals.
    new_replays = []
    for replay, label in zip(bundle.replays, labels, strict=False):
        # dataclasses.replace would lose the cluster_label assignment, so
        # mutate a shallow copy of the field surface.
        from copy import copy as _copy

        clone = _copy(replay)
        object.__setattr__(clone, "cluster_label", int(label))
        new_replays.append(clone)

    return _Bundle(
        replays=new_replays,
        computed_at=bundle.computed_at,
        project_id=bundle.project_id,
    )


__all__ = ["cluster_bundle"]
_ = Any  # keep typing.Any reachable for ImportError-only test paths
