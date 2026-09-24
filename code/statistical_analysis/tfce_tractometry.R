#' 1D Threshold-Free Cluster Enhancement (TFCE) for tractometry node profiles
#'
#' Implements TFCE (Smith & Nichols, 2009) adapted to a 1D array of along-tract
#' nodes (e.g., 100 pyAFQ/AFQ-Insight nodes per tract), combined with a
#' restricted (family-block) permutation test for family-wise error control
#' across nodes -- avoiding both the arbitrary single-threshold problem AND
#' respecting sibling/family clustering assumed by a `(1 | FamilyID)` random
#' effect in the node-wise model.
#'
#' Typical workflow:
#'   1. Fit your node-wise mixed model (e.g., fa ~ IQ + AgeMRI + GestationalAge
#'      + Sex + (1 | FamilyID)) once per node on the real data to get an
#'      observed statistic profile (t-values for IQ), via `nodewise_lmer()`.
#'   2. Convert that profile to a TFCE score profile with `tfce_1d()`.
#'   3. Repeat 1-2 many times with IQ permuted via family-block restricted
#'      permutation (`family_block_permutation()`), recording max |TFCE|
#'      each time (`permutation_test_tfce()`).
#'   4. Use the null distribution of max |TFCE| to assign a corrected
#'      p-value to every node's observed TFCE score.
#'
#' Run separately per tract (one contiguous chain of 100 nodes).

library(lme4)
library(dplyr)

# ---------------------------------------------------------------------------
# 1. Core TFCE computation on a 1D stat profile
# ---------------------------------------------------------------------------

#' TFCE contribution from the positive tail of `stat` only.
#' NA entries (missing nodes) break cluster contiguity rather than counting
#' as zero.
.tfce_one_sign <- function(stat, E, H, n_steps) {
  n <- length(stat)
  tfce <- numeric(n)

  valid <- !is.na(stat)
  if (!any(valid)) return(tfce)

  pos_vals <- stat[valid]
  max_stat <- if (any(pos_vals > 0)) max(pos_vals) else 0
  if (max_stat <= 0) return(tfce)

  thresholds <- seq(max_stat / n_steps, max_stat, length.out = n_steps)
  dh <- if (n_steps > 1) thresholds[2] - thresholds[1] else max_stat

  for (h in thresholds) {
    supra <- ifelse(valid, stat >= h, FALSE)
    if (!any(supra)) next

    # find contiguous runs of TRUE in `supra`
    padded <- c(FALSE, supra, FALSE)
    diffs <- diff(as.integer(padded))
    starts <- which(diffs == 1)       # 1-indexed start of run (in padded coords)
    ends <- which(diffs == -1) - 1    # 1-indexed end of run (in padded coords)
    # padded coords are shifted by +1 relative to `stat`, so index n in
    # `stat` corresponds to index n+1 in `padded` -- starts/ends above are
    # already in `stat`-index terms after the -0 / -1 adjustment: starts
    # (from padded, 1-indexed) map directly to stat 1-indexed start; ends
    # computed as (which(diffs==-1) - 1) map directly to stat 1-indexed end.

    for (i in seq_along(starts)) {
      s <- starts[i]
      e <- ends[i]
      extent <- e - s + 1
      contribution <- (extent ^ E) * (h ^ H) * dh
      tfce[s:e] <- tfce[s:e] + contribution
    }
  }

  tfce
}

#' Compute the signed 1D TFCE score at every node from a node-wise statistic
#' profile (e.g., t-values from a node-wise regression).
#'
#' @param stat Numeric vector of length n_nodes. Node-wise test statistic
#'   (t-value, z-value, etc). Sign matters -- positive and negative effects
#'   are enhanced separately. Use NA for missing/invalid nodes; these break
#'   cluster contiguity rather than being treated as stat = 0.
#' @param E,H TFCE extent and height exponents. E=0.5, H=2.0 are the FSL /
#'   Smith & Nichols (2009) defaults, used here as a reasonable default --
#'   there is no tractometry-specific validated setting, so treat these as
#'   adjustable and consider a sensitivity check across a couple of (E, H)
#'   pairs alongside a cluster/threshold sensitivity check.
#' @param n_steps Number of threshold steps for the numerical integral over
#'   height. 100 is fine-grained enough for a ~100-node profile.
#' @param two_sided If TRUE (default), compute TFCE separately for the
#'   positive and negative tails and return their difference (positive minus
#'   negative), preserving sign. If FALSE, only the positive tail is enhanced.
#' @return Numeric vector of length n_nodes, signed TFCE-enhanced scores.
#'   Nodes that were NA in `stat` remain NA.
tfce_1d <- function(stat, E = 0.5, H = 2.0, n_steps = 100, two_sided = TRUE) {
  stat <- as.numeric(stat)
  pos_tfce <- .tfce_one_sign(stat, E, H, n_steps)

  if (two_sided) {
    neg_tfce <- .tfce_one_sign(-stat, E, H, n_steps)
    tfce <- pos_tfce - neg_tfce
  } else {
    tfce <- pos_tfce
  }

  tfce[is.na(stat)] <- NA
  tfce
}


# ---------------------------------------------------------------------------
# 2. Node-wise mixed-effects regression, run once per node across a tract
# ---------------------------------------------------------------------------

#' Fit a random-intercept mixed model independently at every node of a
#' single tract, and return the node-wise t-value for `var_of_interest`.
#'
#' This is the R/lme4 equivalent of a per-node LMER such as:
#'   fa ~ IQ + AgeMRI + GestationalAge + Sex + (1 | FamilyID)
#' fit separately at each of the 100 nodes.
#'
#' @param df Long-format data for ONE tract: one row per subject per node.
#'   Must contain `node_col`, `group_col`, and all variables in `fixed_formula`.
#' @param fixed_formula A formula string for the FIXED effects only, e.g.
#'   "fa ~ IQ + AgeMRI + GestationalAge + Sex" -- the random-effect term is
#'   added automatically from `group_col`.
#' @param var_of_interest Name of the fixed-effect coefficient (as lme4 will
#'   report it -- check `names(fixef(fit))` once if unsure, e.g. for a
#'   factor term) whose node-wise t-value you want back.
#' @param group_col Column defining the random-intercept grouping variable
#'   (e.g. "FamilyID").
#' @param node_col Column identifying node position (0..n_nodes-1, or
#'   1..n_nodes -- just be consistent with `n_nodes` and the node values
#'   actually present in `df`).
#' @param n_nodes Total number of nodes in the tract (100 for standard
#'   pyAFQ/AFQ-Insight output).
#' @param min_rows Minimum rows required at a node to attempt a fit.
#' @return Numeric vector of length n_nodes; NA at nodes with insufficient
#'   data or a convergence/singularity failure.
nodewise_lmer <- function(df, fixed_formula, var_of_interest, group_col,
                           node_col = "nodeID", n_nodes = 100, min_rows = 10) {
  stat_profile <- rep(NA_real_, n_nodes)
  full_formula <- as.formula(
    paste(fixed_formula, "+ (1 |", group_col, ")")
  )
  node_values <- sort(unique(df[[node_col]]))

  for (node in node_values) {
    node_df <- df[df[[node_col]] == node, ]
    if (nrow(node_df) < min_rows) next

    fit <- tryCatch({
      # suppress the routine singular-fit / convergence messages here;
      # they're summarized separately after the full permutation run
      # rather than printed per node per permutation
      suppressMessages(suppressWarnings(
        lmer(full_formula, data = node_df, REML = TRUE,
             control = lmerControl(check.conv.singular = "ignore"))
      ))
    }, error = function(e) NULL)

    if (is.null(fit)) next

    coefs <- summary(fit)$coefficients
    if (!(var_of_interest %in% rownames(coefs))) next

    # index 1..n_nodes assuming node_values are 0-indexed contiguous or
    # 1-indexed contiguous; store by position to stay robust to either
    idx <- match(node, node_values)
    stat_profile[idx] <- coefs[var_of_interest, "t value"]
  }

  stat_profile
}


# ---------------------------------------------------------------------------
# 3. Restricted permutation respecting family (sibling) clustering
# ---------------------------------------------------------------------------

#' Generate one restricted permutation of `var_of_interest`, preserving
#' family (sibling) clustering, mapped onto every subject.
#'
#' Groups subjects into families, stratifies families by size, and within
#' each size stratum randomly reassigns entire families' *ordered*
#' covariate vectors to other families of the same size. Preserves each
#' family's internal covariate configuration and family composition, while
#' destroying the association between a family's actual FA data and its
#' covariate values -- the null hypothesis of interest. Families with no
#' same-size peer to swap with are left in their original assignment for
#' that draw (an approximation; flag if this affects many subjects).
#'
#' @return Named numeric vector, names = subjectID, values = permuted
#'   var_of_interest for this draw.
family_block_permutation <- function(df, subject_col, family_col, var_of_interest) {
  subj_lookup <- df %>%
    distinct(.data[[subject_col]], .keep_all = TRUE) %>%
    select(all_of(c(subject_col, family_col, var_of_interest)))

  family_sizes <- subj_lookup %>%
    count(.data[[family_col]], name = "fam_size")

  permuted <- setNames(rep(NA_real_, nrow(subj_lookup)), subj_lookup[[subject_col]])

  for (sz in unique(family_sizes$fam_size)) {
    fam_ids <- family_sizes[[family_col]][family_sizes$fam_size == sz]

    if (length(fam_ids) < 2) {
      # nothing to swap with -- leave as-is
      fam_id <- fam_ids[1]
      members <- subj_lookup[subj_lookup[[family_col]] == fam_id, ]
      permuted[members[[subject_col]]] <- members[[var_of_interest]]
      next
    }

    donor_order <- sample(fam_ids)  # random permutation of same-size families

    for (i in seq_along(fam_ids)) {
      recipients <- subj_lookup[subj_lookup[[family_col]] == fam_ids[i], ]
      donor <- subj_lookup[subj_lookup[[family_col]] == donor_order[i], ]
      # row order within subj_lookup is consistent per family, so this
      # preserves sibling-to-sibling relative structure as a swapped unit
      permuted[recipients[[subject_col]]] <- donor[[var_of_interest]]
    }
  }

  permuted
}


# ---------------------------------------------------------------------------
# 4. Full permutation test: build the null distribution of max |TFCE|
# ---------------------------------------------------------------------------

#' Full family-block permutation TFCE pipeline for one tract.
#'
#' @param df Long-format data for ONE tract (one row per subject per node).
#' @param fixed_formula Fixed-effects-only formula string, e.g.
#'   "fa ~ IQ + AgeMRI + GestationalAge + Sex".
#' @param var_of_interest Name of the fixed-effect coefficient to test.
#' @param subject_col,family_col,node_col Column names.
#' @param n_nodes Number of nodes per tract.
#' @param n_permutations Number of permutations (>=1000 recommended for a
#'   real analysis; fewer for a quick sanity check).
#' @param E,H,tfce_n_steps,two_sided,alpha See `tfce_1d()`.
#' @param verbose Print progress every ~10% of permutations.
#' @return A list: observed_stat, observed_tfce, null_max_tfce,
#'   node_pvalues, sig_nodes, alpha, n_na_nodes_observed (diagnostic count
#'   of nodes where the mixed model failed to fit on the real data --
#'   worth checking this isn't unexpectedly high before trusting results).
permutation_test_tfce <- function(df, fixed_formula, var_of_interest,
                                   subject_col = "subjectID",
                                   family_col = "FamilyID",
                                   node_col = "nodeID",
                                   n_nodes = 100,
                                   n_permutations = 1000,
                                   E = 0.5, H = 2.0, tfce_n_steps = 100,
                                   two_sided = TRUE, alpha = 0.05,
                                   random_state = NULL,
                                   verbose = TRUE) {
  if (!is.null(random_state)) set.seed(random_state)

  observed_stat <- nodewise_lmer(df, fixed_formula, var_of_interest,
                                  group_col = family_col, node_col = node_col,
                                  n_nodes = n_nodes)
  observed_tfce <- tfce_1d(observed_stat, E = E, H = H, n_steps = tfce_n_steps,
                            two_sided = two_sided)
  n_na_nodes_observed <- sum(is.na(observed_stat))

  null_max_tfce <- numeric(n_permutations)
  perm_df <- df

  progress_step <- max(1, round(n_permutations / 10))

  for (i in seq_len(n_permutations)) {
    shuffled_map <- family_block_permutation(df, subject_col, family_col, var_of_interest)
    perm_df[[var_of_interest]] <- shuffled_map[as.character(df[[subject_col]])]

    perm_stat <- nodewise_lmer(perm_df, fixed_formula, var_of_interest,
                                group_col = family_col, node_col = node_col,
                                n_nodes = n_nodes)
    perm_tfce <- tfce_1d(perm_stat, E = E, H = H, n_steps = tfce_n_steps,
                          two_sided = two_sided)

    finite_tfce <- perm_tfce[!is.na(perm_tfce)]
    null_max_tfce[i] <- if (length(finite_tfce) > 0) max(abs(finite_tfce)) else 0

    if (verbose && i %% progress_step == 0) {
      cat(sprintf("  permutation %d/%d\n", i, n_permutations))
    }
  }

  node_pvalues <- rep(NA_real_, n_nodes)
  valid <- !is.na(observed_tfce)
  node_pvalues[valid] <- sapply(which(valid), function(n) {
    (sum(null_max_tfce >= abs(observed_tfce[n])) + 1) / (n_permutations + 1)
  })
  sig_nodes <- node_pvalues < alpha

  list(
    observed_stat = observed_stat,
    observed_tfce = observed_tfce,
    null_max_tfce = null_max_tfce,
    node_pvalues = node_pvalues,
    sig_nodes = sig_nodes,
    alpha = alpha,
    n_na_nodes_observed = n_na_nodes_observed
  )
}



# ---------------------------------------------------------------------------
# 5. Synthetic family-structured data, for sanity-checking the pipeline
# ---------------------------------------------------------------------------

make_synthetic_family_data <- function(n_families = 40, n_nodes = 100,
                                        effect_nodes = c(40, 60),
                                        effect_size = 0.06,
                                        sibling_prob = 0.4,
                                        random_state = 0) {
  set.seed(random_state)
  base_profile <- 0.35 + 0.1 * sin(seq(0, pi, length.out = n_nodes))

  rows <- list()
  subj_counter <- 0
  row_i <- 1

  for (fam_i in 1:n_families) {
    fam_id <- sprintf("fam-%03d", fam_i)
    n_sibs <- if (runif(1) < sibling_prob) 2 else 1
    family_intercept <- rnorm(1, 0, 0.015)

    for (s in 1:n_sibs) {
      subj_counter <- subj_counter + 1
      subj_id <- sprintf("sub-%03d", subj_counter)
      iq <- rnorm(1, 100, 15)
      age_mri <- rnorm(1, 30, 8)

      for (node in 0:(n_nodes - 1)) {
        fa <- base_profile[node + 1] + family_intercept + 0.001 * age_mri + rnorm(1, 0, 0.02)
        if (node >= effect_nodes[1] && node <= effect_nodes[2]) {
          fa <- fa + effect_size * (iq - 100) / 15
        }
        rows[[row_i]] <- data.frame(
          subjectID = subj_id, FamilyID = fam_id, nodeID = node,
          fa = fa, IQ = iq, AgeMRI = age_mri
        )
        row_i <- row_i + 1
      }
    }
  }

  bind_rows(rows)
}

if (sys.nframe() == 0) {
  cat("Running synthetic-data sanity check for tfce_tractometry.R ...\n")
  df <- make_synthetic_family_data(n_families = 40, n_nodes = 100, effect_size = 0.08, random_state = 3)
  cat("n subjects:", length(unique(df$subjectID)), " n families:", length(unique(df$FamilyID)), "\n")

  result <- permutation_test_tfce(
    df, fixed_formula = "fa ~ IQ + AgeMRI", var_of_interest = "IQ",
    n_nodes = 100, n_permutations = 15, random_state = 1, verbose = TRUE
  )
  sig_idx <- which(result$sig_nodes) - 1  # convert to 0-indexed node numbers
  cat("\nSignificant nodes (p <", result$alpha, "):", paste(sig_idx, collapse = ", "), "\n")
  cat("True effect simulated at nodes 40-60.\n")
  cat("NA nodes in observed fit:", result$n_na_nodes_observed, "\n")
}


# ---------------------------------------------------------------------------
# 6. Multi-tract wrapper -- loop the full pipeline over a set of tracts
# ---------------------------------------------------------------------------

#' Run the full node-wise LMER + TFCE permutation pipeline across multiple
#' tracts from a single long-format dataframe, and return one tidy results
#' object per tract plus a combined summary table.
#'
#' @param data A long-format dataframe covering ALL tracts, with one row
#'   per subject per node per tract -- e.g., your standard AFQ-Insight/
#'   pyAFQ "tidy" node-level export. Must contain `tract_col`, `node_col`,
#'   `subject_col`, `family_col`, and every variable in `fixed_formula`.
#' @param tracts Character vector of tract names to loop over, as they
#'   appear in `data[[tract_col]]` (e.g. c("CST_L", "CST_R", "ARC_L", ...)).
#' @param fixed_formula Fixed-effects-only formula string, with the outcome
#'   on the left (e.g. "fa ~ IQ + AgeMRI + GestationalAge + Sex").
#' @param var_of_interest Name of the fixed-effect coefficient to test at
#'   every node (e.g. "IQ").
#' @param tract_col Column identifying which tract each row belongs to.
#' @param ... Any other arguments forwarded to `permutation_test_tfce()`
#'   (n_permutations, n_nodes, subject_col, family_col, E, H, alpha,
#'   random_state, verbose, etc.) -- applied identically to every tract.
#' @return A list with:
#'   - `results`: named list of `permutation_test_tfce()` output, one per
#'     tract (access via results[["CST_L"]]$node_pvalues, etc.)
#'   - `summary`: one-row-per-tract data frame with n_significant_nodes,
#'     min_pvalue, n_na_nodes_observed -- a quick first look across all
#'     tracts before diving into any single one's node-level detail.
run_tfce_pipeline_multi_tract <- function(data, tracts, fixed_formula,
                                           var_of_interest,
                                           tract_col = "tractID",
                                           ...) {
  results <- vector("list", length(tracts))
  names(results) <- tracts

  summary_rows <- vector("list", length(tracts))

  for (tr in tracts) {
    cat("\n=== Running tract:", tr, "===\n")
    tract_df <- data[data[[tract_col]] == tr, ]

    if (nrow(tract_df) == 0) {
      warning(sprintf("Tract '%s' has no rows in `data` -- skipping.", tr))
      next
    }

    res <- permutation_test_tfce(
      df = tract_df,
      fixed_formula = fixed_formula,
      var_of_interest = var_of_interest,
      ...
    )
    results[[tr]] <- res

    summary_rows[[tr]] <- data.frame(
      tract = tr,
      n_significant_nodes = sum(res$sig_nodes, na.rm = TRUE),
      min_pvalue = suppressWarnings(min(res$node_pvalues, na.rm = TRUE)),
      n_na_nodes_observed = res$n_na_nodes_observed
    )
  }

  summary_df <- bind_rows(summary_rows)

  list(results = results, summary = summary_df)
}


#' Plot the TFCE result for a single tract (3-panel: stat / TFCE / p-value),
#' as returned by `permutation_test_tfce()` or as one entry of
#' `run_tfce_pipeline_multi_tract()$results`.
plot_tfce_result <- function(result, tract_name = "") {
  n_nodes <- length(result$observed_stat)
  x <- 0:(n_nodes - 1)

  old_par <- par(mfrow = c(3, 1), mar = c(3, 4, 2, 1))
  on.exit(par(old_par))

  plot(x, result$observed_stat, type = "l", ylab = "node t-statistic",
       xlab = "", main = paste(tract_name, "node-wise statistic"))
  abline(h = 0, col = "gray")

  plot(x, result$observed_tfce, type = "l", ylab = "TFCE score", xlab = "")
  abline(h = 0, col = "gray")
  sig_x <- x[result$sig_nodes]
  sig_y <- result$observed_tfce[result$sig_nodes]
  if (length(sig_x) > 0) points(sig_x, sig_y, col = "firebrick", pch = 16, cex = 0.6)

  plot(x, result$node_pvalues, type = "l", ylab = "corrected p-value",
       xlab = "node index (0 = tract start)")
  abline(h = result$alpha, col = "firebrick", lty = 2)
}
