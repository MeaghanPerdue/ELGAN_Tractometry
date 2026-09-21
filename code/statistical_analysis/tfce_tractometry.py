"""
1D Threshold-Free Cluster Enhancement (TFCE) for tractometry node profiles.

Implements TFCE (Smith & Nichols, 2009) adapted to a 1D array of along-tract
nodes (e.g., 100 pyAFQ/AFQ-Insight nodes per tract), combined with a
permutation-based max-statistic test for family-wise error control across
nodes -- avoiding the need to pick an arbitrary single cluster-forming
threshold.

Typical workflow:
    1. Run your node-wise regression (e.g., FA ~ IQ + age + ...) once per
       node on the real data to get an observed statistic profile
       (e.g., t-values for the IQ coefficient), using `nodewise_regression`.
    2. Convert that stat profile to a TFCE score profile with `tfce_1d`.
    3. Repeat steps 1-2 many times with the variable of interest permuted
       across subjects, recording the max |TFCE| each time
       (`permutation_test_tfce`).
    4. Use the null distribution of max |TFCE| to assign a corrected
       p-value to every node's observed TFCE score (`tfce_node_pvalues`).

All functions operate on a single tract at a time (one contiguous chain of
nodes). Run separately per tract.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
from dataclasses import dataclass
from typing import Optional, Callable


# ---------------------------------------------------------------------------
# 1. Core TFCE computation on a 1D stat profile
# ---------------------------------------------------------------------------

def _tfce_one_sign(stat: np.ndarray, E: float, H: float, n_steps: int) -> np.ndarray:
    """
    TFCE contribution from the positive tail of `stat` only.
    `stat` should already be the signed statistic (negative values ignored
    here; call twice, once on stat and once on -stat, to get both tails).

    NaN entries (missing nodes) are treated as breaks in contiguity: a
    cluster never spans across a NaN node.
    """
    n = len(stat)
    tfce = np.zeros(n, dtype=float)

    valid = ~np.isnan(stat)
    if not valid.any():
        return tfce

    max_stat = np.nanmax(stat[valid]) if np.any(stat[valid] > 0) else 0.0
    if max_stat <= 0:
        return tfce

    # integrate from just above 0 to max_stat
    thresholds = np.linspace(max_stat / n_steps, max_stat, n_steps)
    dh = thresholds[1] - thresholds[0] if n_steps > 1 else max_stat

    for h in thresholds:
        supra = np.where(valid, stat >= h, False)
        if not supra.any():
            continue
        # find contiguous runs of True in `supra`
        # pad with False at both ends to detect edges
        padded = np.concatenate(([False], supra, [False]))
        diffs = np.diff(padded.astype(int))
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]  # exclusive end index
        for s, e in zip(starts, ends):
            extent = e - s
            contribution = (extent ** E) * (h ** H) * dh
            tfce[s:e] += contribution

    return tfce


def tfce_1d(
    stat: np.ndarray,
    E: float = 0.5,
    H: float = 2.0,
    n_steps: int = 100,
    two_sided: bool = True,
) -> np.ndarray:
    """
    Compute the signed 1D TFCE score at every node from a node-wise
    statistic profile (e.g., t-values from a node-wise regression).

    Parameters
    ----------
    stat : array of shape (n_nodes,)
        Node-wise test statistic (t-value, z-value, etc.). Sign matters:
        positive and negative effects are enhanced separately. Use NaN for
        missing/invalid nodes (e.g., near tract endpoints) -- these break
        cluster contiguity rather than being treated as stat = 0.
    E, H : float
        TFCE extent and height exponents. E=0.5, H=2.0 are the FSL/
        Smith & Nichols (2009) defaults and are a reasonable default here;
        there's no tractometry-specific validated setting, so treat these
        as adjustable and consider a sensitivity check across a couple of
        (E, H) pairs alongside your threshold sensitivity check.
    n_steps : int
        Number of threshold steps used to numerically approximate the
        integral over height. 100 is a common, safely fine-grained choice
        for a profile of ~100 nodes; increasing it further has little
        effect on the result but costs more compute per permutation.
    two_sided : bool
        If True (default), compute TFCE separately for the positive and
        negative tails and return their difference (positive TFCE minus
        negative TFCE), preserving sign. If False, only the positive tail
        of `stat` is enhanced (use this if you have a directional
        hypothesis and only care about e.g. FA increasing with IQ).

    Returns
    -------
    tfce : array of shape (n_nodes,)
        Signed TFCE-enhanced score at each node. Nodes that were NaN in
        `stat` remain NaN.
    """
    stat = np.asarray(stat, dtype=float)
    pos_tfce = _tfce_one_sign(stat, E, H, n_steps)

    if two_sided:
        neg_tfce = _tfce_one_sign(-stat, E, H, n_steps)
        tfce = pos_tfce - neg_tfce
    else:
        tfce = pos_tfce

    tfce[np.isnan(stat)] = np.nan
    return tfce


# ---------------------------------------------------------------------------
# 2. Node-wise regression, run once per node across a whole tract
# ---------------------------------------------------------------------------

def nodewise_regression(
    df: pd.DataFrame,
    formula: str,
    var_of_interest: str,
    node_col: str = "nodeID",
    n_nodes: int = 100,
    stat_type: str = "tvalue",
) -> np.ndarray:
    """
    Fit `formula` (a statsmodels/patsy formula string, e.g.
    "fa ~ IQ + age + C(sex)") independently at every node of a single tract,
    and return the node-wise statistic for `var_of_interest`.

    This is the function you call once on the real data to get your
    observed profile, and once per permutation (on a copy of `df` with
    `var_of_interest` shuffled) to build the permutation null. It is
    intentionally a thin, generic wrapper around statsmodels OLS so it
    will work directly on a long-format AFQ-Insight/pyAFQ dataframe
    (one row per subject per node) already filtered to a single tract.

    Parameters
    ----------
    df : DataFrame
        Long-format data for ONE tract, one row per subject per node.
        Must contain `node_col`, all variables in `formula`, and one row
        per (subject, node) combination.
    formula : str
        A patsy formula, e.g. "fa ~ IQ + age + C(sex)".
    var_of_interest : str
        Name of the coefficient (as it will appear in the fitted model's
        params/tvalues, e.g. "IQ") whose node-wise statistic you want back.
        For a categorical/dummy-coded term, pass the exact coefficient
        name statsmodels assigns (check `result.params.index` once if
        unsure).
    node_col : str
        Column identifying node position (0..n_nodes-1).
    n_nodes : int
        Total number of nodes in the tract (100 for standard pyAFQ output).
        Nodes with no data, or where the model fails to fit (e.g. due to
        insufficient variation after a permutation), are set to NaN.
    stat_type : {"tvalue", "coef"}
        Whether to return the t-statistic (recommended; comparable across
        nodes regardless of scale) or the raw coefficient.

    Returns
    -------
    stat_profile : array of shape (n_nodes,)
    """
    stat_profile = np.full(n_nodes, np.nan)

    # Parse the formula's design-matrix structure once (using the full
    # dataframe, so all category levels etc. are captured), then reuse
    # that parsed structure per node. This avoids re-parsing the formula
    # string ~n_nodes times per permutation, which is the main speed cost
    # of the naive per-node smf.ols() approach for large permutation counts.
    y_template, X_template = patsy.dmatrices(formula, df, return_type="dataframe")
    y_design_info = y_template.design_info
    X_design_info = X_template.design_info

    if var_of_interest not in X_template.columns:
        raise ValueError(
            f"'{var_of_interest}' not found among fitted coefficient names "
            f"{list(X_template.columns)}. For categorical terms, pass the "
            f"exact patsy-generated name (e.g. 'C(sex)[T.M]')."
        )

    for node in range(n_nodes):
        node_df = df[df[node_col] == node]
        if node_df.shape[0] < 5:  # not enough data to fit meaningfully
            continue
        try:
            y, X = patsy.build_design_matrices(
                [y_design_info, X_design_info], node_df, return_type="dataframe"
            )
            result = sm.OLS(y, X).fit()
            if stat_type == "tvalue":
                stat_profile[node] = result.tvalues[var_of_interest]
            elif stat_type == "coef":
                stat_profile[node] = result.params[var_of_interest]
            else:
                raise ValueError("stat_type must be 'tvalue' or 'coef'")
        except Exception:
            # singular fit, insufficient variation post-permutation, etc.
            # left as NaN -- if this happens for many permutations, check
            # your minimum subjects-per-node and formula complexity.
            continue

    return stat_profile


# ---------------------------------------------------------------------------
# 3. Permutation test: build the null distribution of max |TFCE|
# ---------------------------------------------------------------------------

@dataclass
class TFCEPermutationResult:
    observed_stat: np.ndarray       # node-wise stat on real data
    observed_tfce: np.ndarray       # node-wise TFCE on real data
    null_max_tfce: np.ndarray       # (n_permutations,) null distribution
    node_pvalues: np.ndarray        # corrected p-value per node
    sig_nodes: np.ndarray           # boolean mask, node_pvalues < alpha
    alpha: float


def permutation_test_tfce(
    df: pd.DataFrame,
    formula: str,
    var_of_interest: str,
    subject_col: str = "subjectID",
    node_col: str = "nodeID",
    n_nodes: int = 100,
    n_permutations: int = 1000,
    E: float = 0.5,
    H: float = 2.0,
    tfce_n_steps: int = 100,
    two_sided: bool = True,
    alpha: float = 0.05,
    random_state: Optional[int] = None,
    stat_type: str = "tvalue",
    progress: bool = True,
) -> TFCEPermutationResult:
    """
    Full permutation-based TFCE pipeline for one tract.

    Permutes `var_of_interest` across SUBJECTS (not across subject-node
    rows) so that a given subject's value of `var_of_interest` is shuffled
    as a whole -- this correctly preserves the within-subject structure
    across nodes and any correlation between `var_of_interest` and
    covariates you are NOT permuting. Every other column, including all
    covariates in `formula`, stays attached to its original subject.

    IMPORTANT: this permutes the marginal association between
    `var_of_interest` and everything else. If your model has covariates
    you want to control for exactly (e.g., site, age) and you are
    concerned about confounding between `var_of_interest` and those
    covariates, consider permuting residuals (Freedman-Lane) instead of
    raw values -- this simple version is the standard, adequate approach
    for most single-predictor-of-interest tractometry designs, but flag it
    for review if your design has strong collinearity between
    `var_of_interest` and a covariate.

    Returns
    -------
    TFCEPermutationResult
    """
    rng = np.random.default_rng(random_state)

    # --- observed statistic and TFCE ---
    observed_stat = nodewise_regression(
        df, formula, var_of_interest, node_col=node_col,
        n_nodes=n_nodes, stat_type=stat_type,
    )
    observed_tfce = tfce_1d(observed_stat, E=E, H=H, n_steps=tfce_n_steps,
                             two_sided=two_sided)

    # --- build a subject-level lookup so we can permute var_of_interest
    #     once per subject and broadcast it back to all of that subject's
    #     node rows ---
    subj_values = (
        df[[subject_col, var_of_interest]]
        .drop_duplicates(subset=subject_col)
        .set_index(subject_col)[var_of_interest]
    )
    subjects = subj_values.index.to_numpy()

    null_max_tfce = np.zeros(n_permutations)
    perm_df = df.copy()

    for i in range(n_permutations):
        shuffled_subjects = rng.permutation(subjects)
        shuffled_map = pd.Series(subj_values.values, index=shuffled_subjects)
        # reassign var_of_interest for every row based on shuffled subject
        # labels -- i.e., each subject now "receives" another subject's
        # value of var_of_interest, while keeping their own covariates
        perm_df[var_of_interest] = df[subject_col].map(shuffled_map)

        perm_stat = nodewise_regression(
            perm_df, formula, var_of_interest, node_col=node_col,
            n_nodes=n_nodes, stat_type=stat_type,
        )
        perm_tfce = tfce_1d(perm_stat, E=E, H=H, n_steps=tfce_n_steps,
                             two_sided=two_sided)

        finite = perm_tfce[~np.isnan(perm_tfce)]
        null_max_tfce[i] = np.max(np.abs(finite)) if finite.size else 0.0

        if progress and (i + 1) % max(1, n_permutations // 10) == 0:
            print(f"  permutation {i + 1}/{n_permutations}")

    # --- corrected node-wise p-values via the max-statistic distribution ---
    node_pvalues = np.full(n_nodes, np.nan)
    valid = ~np.isnan(observed_tfce)
    node_pvalues[valid] = [
        (np.sum(null_max_tfce >= abs(observed_tfce[n])) + 1) / (n_permutations + 1)
        for n in np.where(valid)[0]
    ]
    sig_nodes = node_pvalues < alpha

    return TFCEPermutationResult(
        observed_stat=observed_stat,
        observed_tfce=observed_tfce,
        null_max_tfce=null_max_tfce,
        node_pvalues=node_pvalues,
        sig_nodes=sig_nodes,
        alpha=alpha,
    )


# ---------------------------------------------------------------------------
# 4. Plotting
# ---------------------------------------------------------------------------

def plot_tfce_result(result: TFCEPermutationResult, tract_name: str = "",
                      save_path: Optional[str] = None):
    """
    Three-panel summary plot: node-wise stat, node-wise TFCE score with
    significant nodes shaded, and the corrected p-value profile.
    """
    import matplotlib.pyplot as plt

    n_nodes = len(result.observed_stat)
    x = np.arange(n_nodes)

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)

    axes[0].plot(x, result.observed_stat, color="black", lw=1.2)
    axes[0].axhline(0, color="gray", lw=0.5)
    axes[0].set_ylabel("node t-statistic")
    axes[0].set_title(f"{tract_name} node-wise statistic".strip())

    axes[1].plot(x, result.observed_tfce, color="black", lw=1.2)
    axes[1].fill_between(
        x, result.observed_tfce, 0,
        where=result.sig_nodes, color="crimson", alpha=0.4,
        label=f"p < {result.alpha} (permutation-corrected)",
    )
    axes[1].axhline(0, color="gray", lw=0.5)
    axes[1].set_ylabel("TFCE score")
    axes[1].legend(loc="upper right", fontsize=8)

    axes[2].plot(x, result.node_pvalues, color="black", lw=1.2)
    axes[2].axhline(result.alpha, color="crimson", ls="--", lw=1,
                     label=f"alpha = {result.alpha}")
    axes[2].set_ylabel("corrected p-value")
    axes[2].set_xlabel("node index (0 = tract start)")
    axes[2].legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
    return fig


# ---------------------------------------------------------------------------
# 5. Demo with synthetic data (run this file directly to sanity-check)
# ---------------------------------------------------------------------------

def _make_synthetic_data(
    n_subjects: int = 60,
    n_nodes: int = 100,
    effect_nodes: tuple = (40, 60),
    effect_size: float = 0.015,
    random_state: int = 0,
) -> pd.DataFrame:
    """
    Simulate a long-format tractometry dataframe for one tract with a
    true FA~IQ effect confined to nodes 40-60, to sanity check the
    pipeline recovers a plausible cluster in that region.
    """
    rng = np.random.default_rng(random_state)
    iq = rng.normal(100, 15, n_subjects)
    age = rng.normal(30, 8, n_subjects)
    subject_ids = [f"sub-{i:03d}" for i in range(n_subjects)]

    rows = []
    base_profile = 0.35 + 0.1 * np.sin(np.linspace(0, np.pi, n_nodes))
    for s in range(n_subjects):
        for node in range(n_nodes):
            fa = base_profile[node] + 0.001 * age[s] + rng.normal(0, 0.02)
            if effect_nodes[0] <= node <= effect_nodes[1]:
                fa += effect_size * (iq[s] - 100) / 15  # standardized-ish effect
            rows.append({
                "subjectID": subject_ids[s],
                "nodeID": node,
                "fa": fa,
                "IQ": iq[s],
                "age": age[s],
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("Running synthetic-data sanity check for tfce_tractometry.py ...")
    df = _make_synthetic_data()

    result = permutation_test_tfce(
        df=df,
        formula="fa ~ IQ + age",
        var_of_interest="IQ",
        n_nodes=100,
        n_permutations=200,   # use >=1000-5000 for a real analysis
        random_state=1,
        progress=True,
    )

    sig_node_idx = np.where(result.sig_nodes)[0]
    print(f"\nSignificant nodes (p < {result.alpha}): {sig_node_idx.tolist()}")
    print("True effect was simulated at nodes 40-60.")

    fig = plot_tfce_result(result, tract_name="Simulated CST")
    fig.savefig("/home/claude/tfce_demo_output.png", dpi=150)
    print("\nSaved demo plot to tfce_demo_output.png")
