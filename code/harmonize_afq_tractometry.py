#!/usr/bin/env python3
"""
harmonize_afq_tractometry.py

Executable CLI wrapper around the AFQ-Insight / NeuroCombat site-harmonization
workflow (following the AFQ-Insight HBN site-profiles example:
https://tractometry.org/AFQ-Insight/auto_examples/plot_hbn_site_profiles.html).

written with Claude Sonnet 5
2 Sept 2026

Given a single "full" AFQ tract-profile database (one row per subject x tract
x node, wide with all metrics and subject-level covariates included), this
script:

  1. Splits the input into an AFQ-Browser-format nodes.csv and subjects.csv
     (nodes.csv = subjectID/tractID/nodeID + the requested DWI metric columns;
     subjects.csv = subjectID + the requested target/covariate columns,
     de-duplicated to one row per subject).
  2. Loads the split files into an AFQDataset.
  3. Optionally merges small/low-N sites together (e.g. matching scanner +
     protocol) prior to harmonization.
  4. Optionally plots mean tract profiles by site, before harmonization.
  5. Runs NeuroCombat harmonization (afqinsight.neurocombat_sklearn.CombatModel)
     using the specified discrete and continuous covariates.
  6. Optionally plots mean tract profiles by site, after harmonization.
  7. Optionally runs a node-wise regression test on the harmonized data for a
     set of tracts, using a user-specified model formula, and plots the
     regression profiles.

Example
-------
python harmonize_afq_tractometry.py \\
    --input /path/to/ELGAN_afq_prob_filtered.csv \\
    --output-dir /path/to/harmonize \\
    --dwi-metrics dti_fa dti_md \\
    --target-cols site vendor female mri_age gadays bw iq85 mean_fd CNR0_mean CNR1_mean \\
    --exclude-tracts "Left Posterior Arcuate" "Right Posterior Arcuate" "Left Vertical Occipital" "Right Vertical Occipital" \\
    --merge-sites site-140 site-170 \\
    --continuous-covariates mri_age gadays \\
    --discrete-covariates female \\
    --plot-profiles \\
    --regression-tracts "Left Arcuate" "Right Arcuate" "Left Corticospinal" "Right Corticospinal" \\
    --regression-formula "dti_fa ~ C(female)" \\
    --regression-group female \\
    --regression-metric dti_fa
"""

import argparse
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------------------------
# Default subplot layout for pyAFQ waypoint tract names (long-form, as used in ELGAN tractIDs).
# 6x4 grid, left/right mirrored by column, callosal subdivisions each in their own cell.
# Only used when --plot-profiles is passed; override with a different layout in code if your
# tract naming differs.
# --------------------------------------------------------------------------------------------------------
DEFAULT_SUBPLOT_POSITIONS = OrderedDict({
    "Left Inferior Fronto-occipital": (0, 0),
    "UNC_L": (0, 1),
    "UNC_R": (0, 2),
    "Right Inferior Fronto-occipital": (0, 3),

    "Left Anterior Thalamic": (1, 0),
    "CST_L": (1, 1),
    "CST_R": (1, 2),
    "Right Anterior Thalamic": (1, 3),

    "ARC_L": (2, 0),
    "Left Superior Longitudinal": (2, 1),
    "Right Superior Longitudinal": (2, 2),
    "ARC_R": (2, 3),

    "Left Inferior Longitudinal": (3, 0),
    "CGC_L": (3, 1),
    "CGC_R": (3, 2),
    "Right Inferior Longitudinal": (3, 3),

    "Callosum Orbital": (4, 0),
    "Callosum Anterior Frontal": (4, 1),
    "Callosum Superior Frontal": (4, 2),
    "Callosum Motor": (4, 3),

    "Callosum Superior Parietal": (5, 0),
    "Callosum Temporal": (5, 1),
    "Callosum Posterior Parietal": (5, 2),
    "Callosum Occipital": (5, 3),
})


def parse_args():
    p = argparse.ArgumentParser(
        description="Split a full AFQ tract-profile database into nodes/subjects "
                    "files and run NeuroCombat site harmonization via AFQ-Insight.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- I/O ---
    p.add_argument("--input", required=True, type=Path,
                    help="Path to the full AFQ tract-profile CSV (one row per "
                         "subject x tract x node), containing subjectID, tractID, "
                         "nodeID, the DWI metric columns, and the target/covariate columns.")
    p.add_argument("--output-dir", required=True, type=Path,
                    help="Directory to write nodes.csv, subjects.csv, and any plots to.")
    p.add_argument("--subject-id-col", default="subjectID",
                    help="Subject identifier column name (default: subjectID).")
    p.add_argument("--tract-id-col", default="tractID",
                    help="Tract identifier column name (default: tractID).")
    p.add_argument("--node-id-col", default="nodeID",
                    help="Node identifier column name (default: nodeID).")

    # --- column selection ---
    p.add_argument("--dwi-metrics", nargs="+", required=True,
                    help="DWI metric column names to carry into nodes.csv "
                         "(e.g. dti_fa dti_md).")
    p.add_argument("--target-cols", nargs="+", required=True,
                    help="Subject-level covariate/target column names to carry "
                         "into subjects.csv (e.g. site vendor female mri_age gadays).")
    p.add_argument("--exclude-tracts", nargs="*", default=[],
                    help="Tract names to drop from nodes.csv before harmonization "
                         "(e.g. tracts with unreliable segmentation).")

    # --- site handling ---
    p.add_argument("--site-col", default="site",
                    help="Name of the site column within --target-cols (default: site).")
    p.add_argument("--merge-sites", nargs="+", action="append", default=None,
                    metavar="SITE",
                    help="Merge a group of sites into one combined site label prior "
                         "to harmonization. Pass this flag once per group, e.g. "
                         "--merge-sites site-140 site-170 --merge-sites site-A site-B. "
                         "Merged label is the group's site names joined with '_' plus "
                         "'_merged'.")

    # --- harmonization covariates ---
    p.add_argument("--continuous-covariates", nargs="+", required=True,
                    help="Continuous covariate column names for ComBat "
                         "(e.g. mri_age gadays).")
    p.add_argument("--discrete-covariates", nargs="+", required=True,
                    help="Discrete/categorical covariate column names for ComBat "
                         "(e.g. female).")

    # --- plotting ---
    p.add_argument("--plot-profiles", action="store_true",
                    help="Save mean tract-profile plots by site, before and after "
                         "harmonization, to --output-dir.")
    p.add_argument("--subplot-nrows", type=int, default=6)
    p.add_argument("--subplot-ncols", type=int, default=4)

    # --- optional node-wise regression test on harmonized data ---
    p.add_argument("--regression-tracts", nargs="+", default=None,
                    help="If given, run node_wise_regression on these tracts using "
                         "the harmonized data and save a regression-profile figure.")
    p.add_argument("--regression-metric", default=None,
                    help="DWI metric to use for the regression test (e.g. dti_fa). "
                         "Required if --regression-tracts is given.")
    p.add_argument("--regression-formula", default=None,
                    help="Model formula for node_wise_regression "
                         "(e.g. 'dti_fa ~ C(female)'). Required if --regression-tracts is given.")
    p.add_argument("--regression-group", default=None,
                    help="Grouping column for node_wise_regression (e.g. female). "
                         "Required if --regression-tracts is given. This column is "
                         "moved to the front of target_cols, as node_wise_regression requires.")

    args = p.parse_args()

    if args.regression_tracts and not (args.regression_metric and args.regression_formula and args.regression_group):
        p.error("--regression-tracts requires --regression-metric, "
                 "--regression-formula, and --regression-group.")

    return args


def split_input_file(input_path, output_dir, subject_id_col, tract_id_col, node_id_col,
                      dwi_metrics, target_cols, exclude_tracts):
    """Split a full AFQ database CSV into AFQ-Browser-format nodes.csv / subjects.csv."""
    output_dir.mkdir(parents=True, exist_ok=True)

    node_cols = [subject_id_col, tract_id_col, node_id_col] + list(dwi_metrics)
    nodes = pd.read_csv(input_path, usecols=node_cols)
    if exclude_tracts:
        nodes = nodes.query(f"{tract_id_col} not in @exclude_tracts")
    fn_nodes = output_dir / "nodes.csv"
    nodes.to_csv(fn_nodes, index=False)

    subject_cols = [subject_id_col] + [c for c in target_cols if c != subject_id_col]
    subjects = (
        pd.read_csv(input_path, usecols=subject_cols)
        .drop_duplicates()
        .reset_index(drop=True)
    )
    fn_subjects = output_dir / "subjects.csv"
    subjects.to_csv(fn_subjects, index=False)

    print(f"Wrote {len(nodes)} node rows to {fn_nodes}")
    print(f"Wrote {len(subjects)} subject rows to {fn_subjects}")
    return fn_nodes, fn_subjects


def load_dataset(fn_nodes, fn_subjects, dwi_metrics, target_cols):
    from afqinsight import AFQDataset
    return AFQDataset.from_files(
        fn_nodes=str(fn_nodes),
        fn_subjects=str(fn_subjects),
        dwi_metrics=list(dwi_metrics),
        target_cols=list(target_cols),
    )


def apply_site_merges(afqdata, site_col, merge_groups):
    """Relabel groups of sites to a single merged site label. Returns (site_codes, site_uniques, labels)."""
    site_idx = afqdata.target_cols.index(site_col)
    site_labels = afqdata.y[:, site_idx]

    print("Site counts before merge:")
    print(pd.Series(site_labels).value_counts())

    merged_labels = site_labels
    if merge_groups:
        for group in merge_groups:
            merged_name = "_".join(group) + "_merged"
            merged_labels = np.where(np.isin(merged_labels, group), merged_name, merged_labels)

    afqdata.y[:, site_idx] = merged_labels

    site_codes, site_uniques = pd.factorize(merged_labels)

    print("Site counts after merge:")
    print(pd.Series(merged_labels).value_counts())

    return site_codes, site_uniques, merged_labels


def plot_by_site(afqdata_or_harmonized, group_by, output_dir, prefix, subplot_positions, nrows, ncols):
    from afqinsight.plot import plot_tract_profiles
    figs = plot_tract_profiles(
        X=afqdata_or_harmonized,
        group_by=group_by,
        group_by_name="Site",
        figsize=(14, 14),
        subplot_positions=subplot_positions,
        nrows=nrows,
        ncols=ncols,
    )
    for name, fig in figs.items():
        out = output_dir / f"{prefix}_{name}_tract_profiles.png"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(f"Saved {out}")
    return figs


def harmonize(afqdata, site_codes, target_cols, y, discrete_covariate_names, continuous_covariate_names):
    from afqinsight.neurocombat_sklearn import CombatModel

    continuous_idx = [target_cols.index(c) for c in continuous_covariate_names]
    discrete_idx = [target_cols.index(c) for c in discrete_covariate_names]

    continuous_covariates = np.column_stack(
        [y[:, i].astype(float) for i in continuous_idx]
    ) if continuous_idx else np.zeros((y.shape[0], 0))

    discrete_covariates = np.column_stack(
        [y[:, i].astype(float) for i in discrete_idx]
    ) if discrete_idx else np.zeros((y.shape[0], 0))

    combat = CombatModel()
    combat.fit(afqdata.X, site_codes[:, np.newaxis], discrete_covariates, continuous_covariates)

    harmonized = afqdata.copy()
    harmonized.X = combat.transform(
        afqdata.X, site_codes[:, np.newaxis], discrete_covariates, continuous_covariates
    )
    return harmonized


def run_regression_test(harmonized, tracts, metric, formula, group_col, output_dir):
    import matplotlib.pyplot as plt
    from afqinsight.parametric import node_wise_regression
    from afqinsight.plot import plot_regression_profiles

    target_cols = list(harmonized.target_cols)
    group_idx = target_cols.index(group_col)
    if group_idx != 0:
        target_cols[0], target_cols[group_idx] = target_cols[group_idx], target_cols[0]
        harmonized.y[:, [0, group_idx]] = harmonized.y[:, [group_idx, 0]]
    harmonized.target_cols = target_cols

    assert harmonized.target_cols.count(group_col) == 1
    assert harmonized.target_cols[0] == group_col

    num_cols = 2
    nrows = int(np.ceil(len(tracts) / num_cols))
    fig, axes = plt.subplots(nrows=nrows, ncols=num_cols, figsize=(10, 3 * nrows), squeeze=False)

    for i, tract in enumerate(tracts):
        tract_dict = node_wise_regression(harmonized, tract, metric, formula, group=group_col)
        row, col = divmod(i, num_cols)
        axes[row][col].set_title(tract)
        plot_regression_profiles(tract_dict, axes[row][col])

    # hide any unused axes
    for j in range(len(tracts), nrows * num_cols):
        row, col = divmod(j, num_cols)
        axes[row][col].axis("off")

    plt.tight_layout()
    out = output_dir / "regression_profiles.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Saved {out}")


def main():
    args = parse_args()

    fn_nodes, fn_subjects = split_input_file(
        args.input, args.output_dir,
        args.subject_id_col, args.tract_id_col, args.node_id_col,
        args.dwi_metrics, args.target_cols, args.exclude_tracts,
    )

    afqdata = load_dataset(fn_nodes, fn_subjects, args.dwi_metrics, args.target_cols)

    site_codes, site_uniques, merged_labels = apply_site_merges(
        afqdata, args.site_col, args.merge_sites
    )

    if args.plot_profiles:
        plot_by_site(
            afqdata, afqdata.y[:, 0], args.output_dir, "unharmonized",
            DEFAULT_SUBPLOT_POSITIONS, args.subplot_nrows, args.subplot_ncols,
        )

    harmonized = harmonize(
        afqdata, site_codes, afqdata.target_cols, afqdata.y,
        args.discrete_covariates, args.continuous_covariates,
    )

    if args.plot_profiles:
        plot_by_site(
            harmonized, merged_labels, args.output_dir, "harmonized",
            DEFAULT_SUBPLOT_POSITIONS, args.subplot_nrows, args.subplot_ncols,
        )

    if args.regression_tracts:
        run_regression_test(
            harmonized, args.regression_tracts, args.regression_metric,
            args.regression_formula, args.regression_group, args.output_dir,
        )

    # Persist the harmonized dataset (nodes-format) so it can be used downstream
    harmonized_csv = args.output_dir / "harmonized_nodes.csv"
    try:
        harmonized.to_csv(str(harmonized_csv))
        print(f"Saved harmonized dataset to {harmonized_csv}")
    except Exception as e:
        print(f"Note: could not auto-save harmonized dataset via AFQDataset.to_csv "
              f"({e}); harmonized.X / harmonized.y are available in-memory if you "
              f"adapt this script to run interactively.", file=sys.stderr)

    print("Done.")


if __name__ == "__main__":
    main()
