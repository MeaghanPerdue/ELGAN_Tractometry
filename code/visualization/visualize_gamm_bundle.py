"""
Visualize the along-tract effect of FSIQ2 on dti_FA (from the R GAMM
pipeline in gamm_tractometry.R) as a colormap painted along a single
subject's actual bundle streamlines, following the approach shown in
pyAFQ's "Visualizing AFQ derivatives" tutorial
(https://tractometry.org/pyAFQ/tutorials/tutorial_examples/plot_005_viz.html).

Workflow
--------
1. In R: save the per-node GAMM result for one tract to a CSV with at
   least a node index column and an effect-estimate column, e.g.:

       sm <- gammout$results[["Right Inferior Longitudinal"]]$sm
       write.csv(sm[, c("nodeID", ".estimate")],
                 "RILF_FSIQ2_effect.csv", row.names = FALSE)

2. In Python: point this script at that CSV and at one subject's bundle
   file from your BIDS derivatives/afq folder, and it renders the
   bundle's streamlines colored along their length by the node-wise
   FSIQ2 effect.

Two rendering backends are provided:
  - `render_bundle_fury()`: matches the pyAFQ ecosystem's own
    visualization tooling (uses `fury`, GPU-accelerated, interactive-
    capable). This needs a working GPU/WebGPU stack; on a machine
    without one (e.g. some remote/headless servers, some older or
    virtualized GPUs), `fury` 2.x can fail with a WebGPU device error
    (seen in testing as "Unsupported features were requested:
    FLOAT32_FILTERABLE"). This is an environment limitation, not a bug
    in this script -- if you hit it, use the matplotlib fallback below,
    which has no GPU dependency and is guaranteed to render.
  - `render_bundle_matplotlib()`: a dependency-light fallback using
    only matplotlib's Axes3D. Less polished and not interactive, but
    always works, including over SSH/on an HPC login node.

IMPORTANT, fury 2.x API note: unlike the classic VTK-based fury used in
older pyAFQ tutorials (which supported fury.colormap.create_colormap()
to color each point along a line individually), fury 2.x's actor.line()
and actor.streamtube() only accept ONE color PER LINE, not per point.
This script works around that by splitting each streamline into N-1
individual 2-point segments and giving each segment its own color --
tested to confirm this reproduces the same smooth along-tract gradient
effect as the classic per-point approach.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import nibabel as nib
from dipy.io.streamline import load_trk
from dipy.tracking.streamline import set_number_of_points
import matplotlib.cm as cm
import matplotlib.colors as mcolors


# ---------------------------------------------------------------------------
# 1. Load the node-wise GAMM effect from the CSV saved out of R
# ---------------------------------------------------------------------------

def load_nodewise_effect(
    csv_path: str,
    node_col: str = "nodeID",
    value_col: str = ".estimate",
    n_nodes: int = 100,
) -> np.ndarray:
    """
    Load a node-wise scalar (e.g. the GAMM's per-node FSIQ2 effect
    estimate) from a CSV saved out of R, and return it as an array of
    length `n_nodes`, ordered by node index.

    Parameters
    ----------
    csv_path : str
        Path to the CSV (e.g. written via R's `write.csv()` on the `sm`
        data frame from `plot_by_smooth_ci()` / `run_gamm_by_smooth()`).
    node_col, value_col : str
        Column names for node index and the scalar to visualize.
    n_nodes : int
        Expected number of nodes (100 for standard pyAFQ/AFQ-Insight
        tract profiles). Raises if the CSV doesn't have exactly this
        many rows after sorting by node -- better to fail loudly here
        than silently misalign values with bundle points later.

    Returns
    -------
    values : ndarray of shape (n_nodes,)
    """
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
# 2. Load and resample a subject's bundle streamlines
# ---------------------------------------------------------------------------

def load_bundle_streamlines(
    trk_path: str,
    reference_path: str,
    n_points: int = 100,
) -> list[np.ndarray]:
    """
    Load one subject's bundle (.trk) file from a BIDS derivatives/afq
    folder and resample every streamline to `n_points` points, so each
    streamline's point index lines up with the GAMM's node index
    (0 = tract start, n_points-1 = tract end) -- same convention pyAFQ
    itself uses for tract profiles.

    Parameters
    ----------
    trk_path : str
        Path to the bundle file, e.g.
        ".../derivatives/afq/sub-XXX/ses-YYY/clean_bundles/
         sub-XXX_..._desc-prob-afq-<TractName>_tractography.trk"
        (exact filename follows pyAFQ's BIDS-derivative naming; check
        your derivatives/afq/sub-XXX/.../clean_bundles/ or bundles/
        folder for the exact name for your tract of interest).
    reference_path : str
        Path to a NIfTI image in the same space as the .trk file (pyAFQ
        bundles are saved in RASMM/subject dMRI space -- a b0 or FA
        image from the same subject's qsiprep/afq outputs works; e.g.
        ".../derivatives/afq/sub-XXX/.../sub-XXX_..._dwi_b0.nii.gz" or
        the subject's DTI FA map).
    n_points : int
        Number of points per streamline after resampling (100 to match
        standard pyAFQ/AFQ-Insight node count).

    Returns
    -------
    streamlines : list of ndarray, each shape (n_points, 3)
    """
    ref_img = nib.load(reference_path)
    tractogram = load_trk(trk_path, reference_path, bbox_valid_check=False)
    if tractogram is False or tractogram is None:
        raise ValueError(
            f"dipy.io.streamline.load_trk() failed to load '{trk_path}' "
            f"against reference '{reference_path}' -- this usually means the "
            f"reference image's dimensions/affine don't match the header "
            f"baked into the .trk file (dipy logs a 'Dimensions not equal' / "
            f"'Trk file header does not match the provided reference' error "
            f"above this exception rather than raising directly, which is "
            f"why this check exists). Use a reference image from the SAME "
            f"pyAFQ run that produced this .trk file -- e.g. the subject's "
            f"own b0 or model-DTI_FA image in the derivatives/afq folder, "
            f"not an image from a different preprocessing step or subject."
        )
    tractogram.to_rasmm()  # ensure RASMM space, matching pyAFQ's convention
    streamlines = list(tractogram.streamlines)

    if len(streamlines) == 0:
        raise ValueError(f"No streamlines found in {trk_path}")

    resampled = [set_number_of_points(sl, n_points) for sl in streamlines]
    return resampled


# ---------------------------------------------------------------------------
# 3. Build per-node colors from a colormap
# ---------------------------------------------------------------------------

def build_node_colors(
    node_values: np.ndarray,
    cmap_name: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
) -> tuple[np.ndarray, mcolors.Normalize, object]:
    """
    Map a node-wise scalar array to RGB colors via a matplotlib colormap.

    Returns
    -------
    colors : ndarray of shape (n_nodes, 3), RGB in [0, 1]
    norm : the matplotlib Normalize instance used (for building a
        matching colorbar on whichever figure/scene you render into)
    cmap : the matplotlib colormap object used
    """
    vmin = node_values.min() if vmin is None else vmin
    vmax = node_values.max() if vmax is None else vmax
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    cmap = cm.get_cmap(cmap_name)
    colors = cmap(norm(node_values))[:, :3]
    return colors, norm, cmap


# ---------------------------------------------------------------------------
# 4a. Render with fury (matches pyAFQ's own visualization tooling)
# ---------------------------------------------------------------------------

def render_bundle_fury(
    streamlines: list[np.ndarray],
    node_colors: np.ndarray,
    out_path: str = "bundle_fsiq2_effect.png",
    tube_radius: float = 0.3,
    size: tuple[int, int] = (1200, 900),
) -> None:
    """
    Render the bundle colored along its length by `node_colors`, using
    fury (GPU-accelerated; this is pyAFQ's own visualization backend).

    Requires every streamline in `streamlines` to have the same number
    of points as `node_colors` has rows (i.e., already resampled via
    `load_bundle_streamlines(..., n_points=len(node_colors))`).

    If this raises a WebGPU/device error on your machine, use
    `render_bundle_matplotlib()` instead -- see the module docstring.
    """
    from fury import actor, window

    n_points = len(node_colors)
    for sl in streamlines:
        if len(sl) != n_points:
            raise ValueError(
                "Every streamline must have exactly as many points as "
                "node_colors has rows -- resample with "
                f"load_bundle_streamlines(..., n_points={n_points})."
            )

    # fury 2.x's actor.line()/streamtube() color per LINE, not per POINT,
    # so each streamline is split into (n_points - 1) short 2-point
    # segments, each given its own color -- this reproduces the same
    # smooth along-tract gradient as the classic per-point coloring
    # approach from older (VTK-based) fury versions.
    segments = []
    segment_colors = []
    for sl in streamlines:
        for j in range(n_points - 1):
            segments.append(sl[j:j + 2])
            segment_colors.append(node_colors[j])
    segment_colors = np.array(segment_colors)

    line_actor = actor.streamtube(
        lines=segments, colors=segment_colors, radius=tube_radius
    )
    scene = window.Scene()
    scene.add(line_actor)
    window.snapshot(scene=scene, fname=out_path, screen_config=[size])
    print(f"Saved fury rendering to {out_path}")


# ---------------------------------------------------------------------------
# 4b. Render with matplotlib (no GPU dependency, always works)
# ---------------------------------------------------------------------------

def render_bundle_matplotlib(
    streamlines: list[np.ndarray],
    node_colors: np.ndarray,
    norm: mcolors.Normalize,
    cmap,
    out_path: str = "bundle_fsiq2_effect.png",
    cbar_label: str = "Effect of FSIQ2 on dti_FA",
    figsize: tuple[int, int] = (10, 8),
    linewidth: float = 1.5,
    elev: float = 20,
    azim: float = -60,
) -> None:
    """
    Render the bundle colored along its length by `node_colors`, using
    only matplotlib (Axes3D) -- no GPU/display dependency, so this
    always works, including headless (e.g. an HPC login node over SSH).

    Less visually polished than `render_bundle_fury()` (plain line
    segments rather than shaded 3D tubes, not interactive), but a
    reliable fallback or quick-look option.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    n_points = len(node_colors)
    for sl in streamlines:
        if len(sl) != n_points:
            raise ValueError(
                "Every streamline must have exactly as many points as "
                "node_colors has rows -- resample with "
                f"load_bundle_streamlines(..., n_points={n_points})."
            )

    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")

    for sl in streamlines:
        segs = np.stack([sl[:-1], sl[1:]], axis=1)  # (n_points-1, 2, 3)
        lc = Line3DCollection(segs, colors=node_colors[:-1], linewidths=linewidth)
        ax.add_collection3d(lc)

    all_pts = np.vstack(streamlines)
    ax.set_xlim(all_pts[:, 0].min(), all_pts[:, 0].max())
    ax.set_ylim(all_pts[:, 1].min(), all_pts[:, 1].max())
    ax.set_zlim(all_pts[:, 2].min(), all_pts[:, 2].max())
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
    # --- adjust these paths for your data ---
    CSV_PATH = "RILF_FSIQ2_effect.csv"       # saved from R, see module docstring
    SUBJECT = "sub-XXXX"
    SESSION = "ses-YYYY"                      # omit/adjust if your BIDS tree has no session level
    AFQ_DERIV = f"derivatives/afq/{SUBJECT}/{SESSION}"
    TRK_PATH = (
        f"{AFQ_DERIV}/clean_bundles/"
        f"{SUBJECT}_{SESSION}_..._desc-prob-afq-RILF_tractography.trk"
    )  # fill in the exact filename -- check your clean_bundles/ or bundles/ folder
    REFERENCE_PATH = f"{AFQ_DERIV}/{SUBJECT}_{SESSION}_..._dwi_b0.nii.gz"
    N_NODES = 100

    node_values = load_nodewise_effect(CSV_PATH, n_nodes=N_NODES)
    streamlines = load_bundle_streamlines(TRK_PATH, REFERENCE_PATH, n_points=N_NODES)
    node_colors, norm, cmap = build_node_colors(node_values, cmap_name="viridis")

    try:
        render_bundle_fury(streamlines, node_colors, out_path="RILF_FSIQ2_effect_fury.png")
    except Exception as e:
        print(f"fury rendering failed ({e}); falling back to matplotlib.")
        render_bundle_matplotlib(
            streamlines, node_colors, norm, cmap,
            out_path="RILF_FSIQ2_effect_matplotlib.png",
        )
