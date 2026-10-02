"""
Visualize the along-tract effect of FSIQ2 on dti_FA (from the R GAMM
pipeline in gamm_tractometry.R) as a colormap painted along a single
subject's TRACT CORE -- one representative centroid streamline summarizing
the whole bundle -- rather than on every individual streamline.
Written with Claude Sonnet 5

This is a simpler, cleaner companion to visualize_gamm_bundle.py: instead
of coloring potentially hundreds of streamlines (which required splitting
each one into many short segments to work around fury 2.x's per-line-only
coloring, and could hit a GPU shadow-texture size limit on some systems
with large bundles), only ONE streamline is colored here -- a small
enough number of segments (n_nodes - 1, ~99) that the same fury GPU path
is far more likely to work even where the full-bundle version didn't, on
top of being an easier plot to read on its own.

Workflow
--------
1. In R: save the per-node GAMM result for one tract to a CSV (same as
   for visualize_gamm_bundle.py):

       sm <- gammout$results[["Right Inferior Longitudinal"]]$sm
       write.csv(sm[, c("nodeID", ".estimate")],
                 "RILF_FSIQ2_effect.csv", row.names = FALSE)

2. In Python: point this script at that CSV and at one subject's bundle
   file, and it computes that subject's tract core and colors it by the
   node-wise FSIQ2 effect.

Two rendering backends, as in visualize_gamm_bundle.py:
  - `render_core_fury()`: GPU-accelerated, matches pyAFQ's own
    visualization tooling. Needs a working GPU/WebGPU stack.
  - `render_core_matplotlib()`: no GPU dependency, always works
    (including headless/HPC); use this if fury raises any GPU/device
    error on your machine -- confirmed in practice that some systems'
    fury/pygfx/wgpu stack has issues even without the large-segment-count
    problem the full-bundle version could hit, so there's no guarantee
    fury will work here either even though the segment count is much
    smaller -- treat it as worth trying, not as guaranteed to work.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import nibabel as nib
from dipy.io.streamline import load_trk
from dipy.tracking.streamline import set_number_of_points, orient_by_streamline
from dipy.segment.clustering import QuickBundles
from dipy.segment.featurespeed import ResampleFeature
from dipy.segment.metricspeed import AveragePointwiseEuclideanMetric
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors


# ---------------------------------------------------------------------------
# 1. Load the node-wise GAMM effect from the CSV saved out of R
#    (identical to visualize_gamm_bundle.py)
# ---------------------------------------------------------------------------

def load_nodewise_effect(
    csv_path: str,
    node_col: str = "nodeID",
    value_col: str = ".estimate",
    n_nodes: int = 100,
) -> np.ndarray:
    """Load a node-wise scalar from a CSV saved out of R. See
    visualize_gamm_bundle.py's version of this function for full docs."""
    df = pd.read_csv(csv_path)
    if node_col not in df.columns or value_col not in df.columns:
        raise ValueError(
            f"CSV must contain columns '{node_col}' and '{value_col}'. "
            f"Found columns: {list(df.columns)}"
        )
    df = df.sort_values(node_col)
    if len(df) != n_nodes:
        raise ValueError(
            f"Expected {n_nodes} rows (one per node) after sorting by "
            f"'{node_col}', found {len(df)}. Check the CSV covers exactly "
            f"one tract's full node range with no duplicates/gaps."
        )
    return df[value_col].to_numpy()


# ---------------------------------------------------------------------------
# 2. Compute a subject's tract core (centroid streamline)
# ---------------------------------------------------------------------------

def compute_tract_core(
    trk_path: str,
    reference_path: str,
    n_points: int = 100,
) -> np.ndarray:
    """
    Load one subject's bundle and compute its tract core: a single
    representative centroid streamline summarizing the whole bundle,
    via QuickBundles with threshold=inf (so every streamline in the
    bundle forms one cluster and contributes to one centroid) -- the
    same clustering approach dipy's own AFQ tract-profile tutorial uses
    to build a reference/"standard" streamline
    (https://docs.dipy.org/stable/examples_built/streamline_analysis/afq_tract_profiles.html),
    just applied to this subject's own bundle rather than an external
    atlas bundle.

    Every streamline is first oriented consistently (via
    orient_by_streamline, against that same centroid, re-computed once
    streamlines are resampled) before being folded into the centroid --
    without this, streamlines running in inconsistent directions would
    partially cancel out rather than average into a clean core.

    Parameters
    ----------
    trk_path, reference_path : str
        See visualize_gamm_bundle.load_bundle_streamlines() -- same
        requirements (reference image must be in the same space as the
        .trk file, from the same subject/pyAFQ run).
    n_points : int
        Number of points for the resulting core streamline (100 to match
        standard pyAFQ/AFQ-Insight node count -- must match the length
        of whatever node-wise array you plan to color it with).

    Returns
    -------
    core : ndarray of shape (n_points, 3)
    """
    tractogram = load_trk(trk_path, reference_path, bbox_valid_check=False)
    if tractogram is False or tractogram is None:
        raise ValueError(
            f"dipy.io.streamline.load_trk() failed to load '{trk_path}' "
            f"against reference '{reference_path}' -- usually a reference "
            f"image dimension/affine mismatch. Use a reference image from "
            f"the SAME pyAFQ run that produced this .trk file."
        )
    tractogram.to_rasmm()
    streamlines = list(tractogram.streamlines)
    if len(streamlines) == 0:
        raise ValueError(f"No streamlines found in {trk_path}")

    resampled = [set_number_of_points(sl, n_points) for sl in streamlines]

    feature = ResampleFeature(nb_points=n_points)
    metric = AveragePointwiseEuclideanMetric(feature)
    qb = QuickBundles(threshold=np.inf, metric=metric)

    # first pass: rough centroid to establish a consistent orientation
    rough_centroid = qb.cluster(resampled).centroids[0]
    oriented = orient_by_streamline(resampled, rough_centroid)

    # second pass: recompute the centroid from consistently-oriented
    # streamlines -- this is the actual tract core returned
    core = qb.cluster(oriented).centroids[0]
    return np.asarray(core)


# ---------------------------------------------------------------------------
# 3. Build per-node colors from a colormap (identical to visualize_gamm_bundle.py)
# ---------------------------------------------------------------------------

def build_node_colors(
    node_values: np.ndarray,
    cmap_name: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
) -> tuple[np.ndarray, mcolors.Normalize, object]:
    """Map a node-wise scalar array to RGB colors via a matplotlib colormap."""
    vmin = node_values.min() if vmin is None else vmin
    vmax = node_values.max() if vmax is None else vmax
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.get_cmap(cmap_name)
    colors = cmap(norm(node_values))[:, :3]
    return colors, norm, cmap


# ---------------------------------------------------------------------------
# 4a. Render with fury
# ---------------------------------------------------------------------------

def render_core_fury(
    core: np.ndarray,
    node_colors: np.ndarray,
    out_path: str = "core_fsiq2_effect.png",
    tube_radius: float = 0.8,
    size: tuple[int, int] = (1200, 900),
) -> None:
    """
    Render the tract core colored along its length by `node_colors`,
    using fury. Only ~n_points-1 segments are needed (one streamline),
    which is far below the segment count that could hit a GPU shadow-
    texture size limit when coloring a whole bundle -- see
    visualize_gamm_bundle.py's render_bundle_fury() docstring for that
    issue. This makes fury considerably more likely to work here even
    on a system where the full-bundle version failed, though it's not
    guaranteed, since the underlying GPU/driver stack issue could be
    unrelated to segment count on some systems.

    `material="phong"` (fury's default, left unspecified here) is used
    deliberately -- `material="basic"` is NOT currently supported by
    fury's GPU streamtube backend (confirmed: raises "GPU streamtubes
    currently support material='phong' only.").

    tube_radius defaults larger than in visualize_gamm_bundle.py (0.8
    vs 0.3) since a single tube representing the whole tract benefits
    from being more visually prominent than one streamline among many.
    Adjust to match your data's spatial scale.
    """
    from fury import actor, window

    n_points = len(node_colors)
    if len(core) != n_points:
        raise ValueError(
            f"core has {len(core)} points but node_colors has {n_points} rows -- "
            f"these must match. Recompute with compute_tract_core(..., n_points={n_points})."
        )

    segments = [core[j:j + 2] for j in range(n_points - 1)]
    segment_colors = node_colors[:-1]

    tube_actor = actor.streamtube(lines=segments, colors=segment_colors, radius=tube_radius)
    scene = window.Scene()
    scene.add(tube_actor)
    window.snapshot(scene=scene, fname=out_path, screen_config=[size])
    print(f"Saved fury rendering to {out_path}")


# ---------------------------------------------------------------------------
# 4b. Render with matplotlib
# ---------------------------------------------------------------------------

def render_core_matplotlib(
    core: np.ndarray,
    node_colors: np.ndarray,
    norm: mcolors.Normalize,
    cmap,
    out_path: str = "core_fsiq2_effect.png",
    cbar_label: str = "Effect of FSIQ2 on dti_FA",
    figsize: tuple[int, int] = (10, 8),
    linewidth: float = 4.0,
    elev: float = 20,
    azim: float = -60,
) -> None:
    """
    Render the tract core colored along its length by `node_colors`,
    using only matplotlib -- no GPU dependency, always works.

    linewidth defaults thicker than visualize_gamm_bundle.py's fallback
    (4.0 vs 1.5) since a single core line needs to be visually
    prominent on its own, unlike one line among a full bundle.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    n_points = len(node_colors)
    if len(core) != n_points:
        raise ValueError(
            f"core has {len(core)} points but node_colors has {n_points} rows -- "
            f"these must match. Recompute with compute_tract_core(..., n_points={n_points})."
        )

    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")

    segs = np.stack([core[:-1], core[1:]], axis=1)  # (n_points-1, 2, 3)
    lc = Line3DCollection(segs, colors=node_colors[:-1], linewidths=linewidth)
    ax.add_collection3d(lc)

    ax.set_xlim(core[:, 0].min(), core[:, 0].max())
    ax.set_ylim(core[:, 1].min(), core[:, 1].max())
    ax.set_zlim(core[:, 2].min(), core[:, 2].max())
    ax.set_axis_off()
    ax.view_init(elev=elev, azim=azim)

    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.6, label=cbar_label)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved matplotlib rendering to {out_path}")


# ---------------------------------------------------------------------------
# 5. Example usage -- adjust paths for your BIDS derivatives/afq layout
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    CSV_PATH = "results/FSIQ_AFQprob/GAMM_nodewise_results/RILF_FSIQ2_effect.csv"
    SUBJECT = "sub-E1600121J"
    SESSION = "ses-03"
    AFQ_DERIV = f"data/site-160/derivatives/afq/{SUBJECT}/{SESSION}"
    TRK_PATH = (
        f"{AFQ_DERIV}/dwi/bundles/"
        f"{SUBJECT}_{SESSION}_desc-RightInferiorLongitudinal_tractography.trk"
    )
    REFERENCE_PATH = f"{AFQ_DERIV}/dwi/{SUBJECT}_{SESSION}_b0ref.nii.gz"
    N_NODES = 100

    node_values = load_nodewise_effect(CSV_PATH, n_nodes=N_NODES)
    core = compute_tract_core(TRK_PATH, REFERENCE_PATH, n_points=N_NODES)
    node_colors, norm, cmap = build_node_colors(node_values, cmap_name="viridis")

    try:
        render_core_fury(core, node_colors, out_path="RILF_FSIQ2_core_fury.png")
    except Exception as e:
        print(f"fury rendering failed ({e}); falling back to matplotlib.")
        render_core_matplotlib(
            core, node_colors, norm, cmap,
            out_path="RILF_FSIQ2_core_matplotlib.png",
        )