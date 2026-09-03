#!/usr/bin/env python3
"""
node_wise_regression_cli.py

Reload a harmonized AFQ tractometry dataset that was saved by
harmonize_afq_tractometry.py (as an AFQ-Browser-format nodes.csv /
subjects.csv pair) and run afqinsight's node_wise_regression on one or more
tracts, saving a regression-profile figure and (optionally) the per-node
statistics to CSV.

This is deliberately a separate script/session from harmonization: once
harmonized_nodes.csv / harmonized_subjects.csv exist, you don't need to
re-run ComBat to test a new model formula or a new set of tracts.

Example
-------
python node_wise_regression_cli.py \\
    --fn-nodes /path/to/harmonize/harmonized_nodes.csv \\
    --fn-subjects /path/to/harmonize/harmonized_subjects.csv \\
    --dwi-metrics dti_fa dti_md \\
    --target-cols site vendor female mri_age gadays bw iq85 mean_fd CNR0_mean CNR1_mean \\
    --tracts "Left Arcuate" "Right Arcuate" "Left Corticospinal" "Right Corticospinal" \\
    --metric dti_fa \\
    --formula "dti_fa ~ C(female)" \\
    --group female \\
    --output-dir /path/to/harmonize/regression_out
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args():
    p = argparse.ArgumentParser(
        description="Run afqinsight node_wise_regression on a saved harmonized "
                    "AFQ tractometry dataset (nodes.csv + subjects.csv).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--fn-nodes", required=True, type=Path,
                    help="Path to the harmonized nodes.csv (from harmonize_afq_tractometry.py).")
    p.add_argument("--fn-subjects", required=True, type=Path,
                    help="Path to the harmonized subjects.csv (from harmonize_afq_tractometry.py).")
    p.add_argument("--dwi-metrics", nargs="+", required=True,
                    help="DWI metric column names present in nodes.csv (e.g. dti_fa dti_md). "
                         "Must match what was used when the dataset was harmonized.")
    p.add_argument("--target-cols", nargs="+", required=True,
                    help="Subject-level covariate/target column names present in subjects.csv. "
                         "Must match what was used when the dataset was harmonized.")
    p.add_argument("--subject-id-col", default="subjectID",
                    help="Subject identifier column name (default: subjectID).")

    p.add_argument("--tracts", nargs="+", required=True,
                    help="Tract names to run node-wise regression on.")
    p.add_argument("--metric", required=True,
                    help="DWI metric to use as the regression outcome (e.g. dti_fa).")
    p.add_argument("--formula", required=True,
                    help="Model formula, e.g. 'dti_fa ~ C(female)'. See statsmodels formula syntax.")
    p.add_argument("--group", required=True,
                    help="Grouping/effect-of-interest column (must be in --target-cols). "
                         "Moved to the front of target_cols, as node_wise_regression requires.")
    p.add_argument("--lme", action="store_true",
                    help="Fit a linear mixed-effects model instead of OLS at each node.")
    p.add_argument("--rand-eff", default="subjectID",
                    help="Random-effect grouping column for --lme (default: subjectID).")

    p.add_argument("--output-dir", required=True, type=Path,
                    help="Directory to write the regression-profile figure and stats CSV to.")
    p.add_argument("--ncols", type=int, default=2,
                    help="Number of subplot columns for the regression-profile figure (default: 2).")

    return p.parse_args()


def load_harmonized_dataset(fn_nodes, fn_subjects, dwi_metrics, target_cols):
    from afqinsight import AFQDataset
    return AFQDataset.from_files(
        fn_nodes=str(fn_nodes),
        fn_subjects=str(fn_subjects),
        dwi_metrics=list(dwi_metrics),
        target_cols=list(target_cols),
    )


def put_group_first(dataset, group_col):
    target_cols = list(dataset.target_cols)
    group_idx = target_cols.index(group_col)
    if group_idx != 0:
        target_cols[0], target_cols[group_idx] = target_cols[group_idx], target_cols[0]
        dataset.y[:, [0, group_idx]] = dataset.y[:, [group_idx, 0]]
    dataset.target_cols = target_cols
    assert dataset.target_cols.count(group_col) == 1
    assert dataset.target_cols[0] == group_col


def tract_dict_to_dataframe(tract_dict):
    """Flatten a node_wise_regression() result dict into a per-node stats DataFrame."""
    n_nodes = len(tract_dict["pvals"])
    reject_mask = np.zeros(n_nodes, dtype=bool)
    reject_mask[tract_dict["reject_idx"]] = True
    return pd.DataFrame({
        "node": np.arange(n_nodes),
        "reference_coef": tract_dict["reference_coefs"],
        "group_coef": tract_dict["group_coefs"],
        "reference_ci_lo": tract_dict["reference_CI"][:, 0],
        "reference_ci_hi": tract_dict["reference_CI"][:, 1],
        "group_ci_lo": tract_dict["group_CI"][:, 0],
        "group_ci_hi": tract_dict["group_CI"][:, 1],
        "pval": tract_dict["pvals"],
        "reject_null": reject_mask,
    })


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_harmonized_dataset(
        args.fn_nodes, args.fn_subjects, args.dwi_metrics, args.target_cols
    )
    put_group_first(dataset, args.group)

    from afqinsight.parametric import node_wise_regression
    from afqinsight.plot import plot_regression_profiles
    import matplotlib.pyplot as plt

    nrows = int(np.ceil(len(args.tracts) / args.ncols))
    fig, axes = plt.subplots(nrows=nrows, ncols=args.ncols, figsize=(5 * args.ncols, 3 * nrows), squeeze=False)

    for i, tract in enumerate(args.tracts):
        tract_dict = node_wise_regression(
            dataset, tract, args.metric, args.formula,
            group=args.group, lme=args.lme, rand_eff=args.rand_eff,
        )

        row, col = divmod(i, args.ncols)
        axes[row][col].set_title(tract)
        plot_regression_profiles(tract_dict, axes[row][col])

        stats_df = tract_dict_to_dataframe(tract_dict)
        stats_csv = args.output_dir / f"regression_stats_{tract.replace(' ', '_')}.csv"
        stats_df.to_csv(stats_csv, index=False)
        print(f"Saved {stats_csv}")

    # hide unused axes
    for j in range(len(args.tracts), nrows * args.ncols):
        row, col = divmod(j, args.ncols)
        axes[row][col].axis("off")

    plt.tight_layout()
    fig_path = args.output_dir / "regression_profiles.png"
    fig.savefig(fig_path, dpi=300, bbox_inches="tight")
    print(f"Saved {fig_path}")

    print("Done.")


if __name__ == "__main__":
    main()
