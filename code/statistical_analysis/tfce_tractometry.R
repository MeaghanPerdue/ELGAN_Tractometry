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
  n_na_nodes_observed <- sum(is.na(observed_stat))

  if (n_na_nodes_observed == n_nodes) {
    stop(paste0(
      "nodewise_lmer() failed to fit a model at EVERY node (", n_nodes, "/", n_nodes, " NA) ",
      "-- something is wrong before this ever reaches permutation testing. ",
      "Most likely causes, in order of likelihood:\n",
      "  1. `fixed_formula` variable name(s) with too many NAs (e.g., missing bw/gadays for ",
      "     many subjects) pushing per-node sample size below `min_rows` (default 10) at every node.\n",
      "  2. `family_col` ('", family_col, "') has near-singular structure for this tract's subset ",
      "     (e.g., almost every family is a singleton after filtering), causing lmer() to fail to ",
      "     converge or to error on the random-intercept term at every node.\n",
      "  3. A typo/case mismatch between a variable name in `fixed_formula` and the actual column ",
      "     name in `df` (check with names(df)).\n",
      "  4. The tract subset itself is unexpectedly small or malformed -- check nrow(df), ",
      "     length(unique(df$", node_col, ")), and table(df$", family_col, ") on just this tract's ",
      "     data before re-running.\n",
      "Try running nodewise_lmer() directly on a single node's subset with tryCatch(..., error = ",
      "function(e) print(e)) (rather than the silent NULL fallback it uses inside the loop) to see ",
      "the actual lme4 error message."
    ))
  }

  observed_tfce <- tfce_1d(observed_stat, E = E, H = H, n_steps = tfce_n_steps,
                            two_sided = two_sided)

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
  if (any(valid)) {
    node_pvalues[valid] <- vapply(which(valid), function(n) {
      (sum(null_max_tfce >= abs(observed_tfce[n])) + 1) / (n_permutations + 1)
    }, FUN.VALUE = numeric(1))
  }
  sig_nodes <- node_pvalues < alpha

  if (n_na_nodes_observed > 0) {
    warning(sprintf(
      "%d of %d nodes failed to fit (NA) for this tract -- results below are based only on the %d nodes that fit. Check n_na_nodes_observed before trusting this tract's results.",
      n_na_nodes_observed, n_nodes, n_nodes - n_na_nodes_observed
    ))
  }

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
# 4b. Parallelized permutation test (future.apply), with chunked checkpointing
# ---------------------------------------------------------------------------

#' Same as `permutation_test_tfce()`, but runs the permutation loop in
#' parallel across `n_workers` local R processes via future.apply, and saves
#' intermediate progress to disk in chunks so a crash/interruption during a
#' long run (e.g., 5000 permutations) doesn't lose completed work.
#'
#' Reproducibility note: parallel results will NOT numerically match a serial
#' `permutation_test_tfce()` run with the same `random_state` -- future.seed's
#' independent-stream RNG (L'Ecuyer-CMRG) differs from base R's serial
#' stream. They WILL be reproducible across reruns of this parallel function
#' with the same `random_state`, `n_permutations`, and `n_workers`.
#'
#' @param n_workers Number of parallel worker processes. Leave some headroom
#'   below your machine's full core count (e.g. 8 on a 10-12 core M2 Pro) so
#'   the machine stays responsive.
#' @param chunk_size Permutations per checkpoint. Progress is saved to
#'   `checkpoint_path` after every chunk.
#' @param checkpoint_path Optional .rds file path. If it already exists and
#'   contains a partial run matching this call's settings, resumes from
#'   there instead of starting over -- useful after an interrupted run.
#' @return Same structure as `permutation_test_tfce()`.
permutation_test_tfce_parallel <- function(df, fixed_formula, var_of_interest,
                                            subject_col = "subjectID",
                                            family_col = "FamilyID",
                                            node_col = "nodeID",
                                            n_nodes = 100,
                                            n_permutations = 5000,
                                            E = 0.5, H = 2.0, tfce_n_steps = 100,
                                            two_sided = TRUE, alpha = 0.05,
                                            random_state = NULL,
                                            n_workers = 8,
                                            chunk_size = 500,
                                            checkpoint_path = NULL) {
  library(future)
  library(future.apply)

  # keep BLAS from oversubscribing underneath worker-level parallelism --
  # each lmer() fit is tiny, so multithreaded linear algebra buys nothing
  # here and just fights with the worker processes for cores
  old_omp <- Sys.getenv("OMP_NUM_THREADS", unset = NA)
  old_veclib <- Sys.getenv("VECLIB_MAXIMUM_THREADS", unset = NA)
  Sys.setenv(OMP_NUM_THREADS = "1", VECLIB_MAXIMUM_THREADS = "1")

  old_plan <- plan()
  plan(multisession, workers = n_workers)
  on.exit({
    plan(old_plan)
    if (!is.na(old_omp)) Sys.setenv(OMP_NUM_THREADS = old_omp)
    if (!is.na(old_veclib)) Sys.setenv(VECLIB_MAXIMUM_THREADS = old_veclib)
  }, add = TRUE)

  observed_stat <- nodewise_lmer(df, fixed_formula, var_of_interest,
                                  group_col = family_col, node_col = node_col,
                                  n_nodes = n_nodes)
  n_na_nodes_observed <- sum(is.na(observed_stat))

  if (n_na_nodes_observed == n_nodes) {
    stop("nodewise_lmer() failed to fit a model at EVERY node -- see permutation_test_tfce()'s ",
         "error message for troubleshooting steps (run the serial version first to see it in full).")
  }

  observed_tfce <- tfce_1d(observed_stat, E = E, H = H, n_steps = tfce_n_steps,
                            two_sided = two_sided)

  # resume from checkpoint if one exists and matches this call's settings
  null_max_tfce <- numeric(0)
  start_perm <- 1
  if (!is.null(checkpoint_path) && file.exists(checkpoint_path)) {
    ckpt <- readRDS(checkpoint_path)
    # resume whenever the settings that determine the null distribution's
    # meaning match (seed, formula, variable of interest) -- n_permutations
    # is deliberately NOT part of this check, since asking for MORE total
    # permutations than a checkpoint currently has is exactly the normal
    # resume use case (e.g., extending a 1000-permutation checkpoint to
    # 5000) and should not be treated as a settings mismatch
    settings_match <- identical(ckpt$settings$random_state, random_state) &&
      identical(ckpt$settings$fixed_formula, fixed_formula) &&
      identical(ckpt$settings$var_of_interest, var_of_interest)

    if (settings_match && length(ckpt$null_max_tfce) < n_permutations) {
      null_max_tfce <- ckpt$null_max_tfce
      start_perm <- length(null_max_tfce) + 1
      cat(sprintf("Resuming from checkpoint: %d/%d permutations already done.\n",
                  length(null_max_tfce), n_permutations))
    } else if (settings_match && length(ckpt$null_max_tfce) >= n_permutations) {
      # checkpoint already covers (or exceeds) the requested count
      null_max_tfce <- ckpt$null_max_tfce[seq_len(n_permutations)]
      start_perm <- n_permutations + 1
      cat(sprintf("Checkpoint already has %d permutations (>= the %d requested) -- using it as-is.\n",
                  length(ckpt$null_max_tfce), n_permutations))
    } else {
      cat("Checkpoint found but random_state/formula/var_of_interest don't match this call -- starting fresh.\n")
    }
  }

  if (start_perm <= n_permutations) {
    chunk_starts <- seq(start_perm, n_permutations, by = chunk_size)

    for (chunk_start in chunk_starts) {
      chunk_end <- min(chunk_start + chunk_size - 1, n_permutations)
      chunk_ids <- chunk_start:chunk_end

      if (!is.null(random_state)) set.seed(random_state)

      chunk_results <- future_sapply(chunk_ids, function(i) {
        shuffled_map <- family_block_permutation(df, subject_col, family_col, var_of_interest)
        perm_df <- df
        perm_df[[var_of_interest]] <- shuffled_map[as.character(df[[subject_col]])]

        perm_stat <- nodewise_lmer(perm_df, fixed_formula, var_of_interest,
                                    group_col = family_col, node_col = node_col,
                                    n_nodes = n_nodes)
        perm_tfce <- tfce_1d(perm_stat, E = E, H = H, n_steps = tfce_n_steps,
                              two_sided = two_sided)
        finite_tfce <- perm_tfce[!is.na(perm_tfce)]
        if (length(finite_tfce) > 0) max(abs(finite_tfce)) else 0
      }, future.seed = TRUE, future.packages = c("lme4", "dplyr"))

      null_max_tfce <- c(null_max_tfce, chunk_results)

      cat(sprintf("  completed permutations %d-%d of %d\n", chunk_start, chunk_end, n_permutations))

      if (!is.null(checkpoint_path)) {
        saveRDS(list(
          null_max_tfce = null_max_tfce,
          settings = list(n_permutations = n_permutations, random_state = random_state,
                           fixed_formula = fixed_formula, var_of_interest = var_of_interest)
        ), checkpoint_path)
      }
    }
  }

  node_pvalues <- rep(NA_real_, n_nodes)
  valid <- !is.na(observed_tfce)
  if (any(valid)) {
    node_pvalues[valid] <- vapply(which(valid), function(n) {
      (sum(null_max_tfce >= abs(observed_tfce[n])) + 1) / (n_permutations + 1)
    }, FUN.VALUE = numeric(1))
  }
  sig_nodes <- node_pvalues < alpha

  list(
    observed_stat = observed_stat, observed_tfce = observed_tfce,
    null_max_tfce = null_max_tfce, node_pvalues = node_pvalues,
    sig_nodes = sig_nodes, alpha = alpha,
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


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 6b. Multi-tract wrapper, parallelized ACROSS TRACTS (not across permutations)
# ---------------------------------------------------------------------------

#' Same job as `run_tfce_pipeline_multi_tract()`, but runs each tract's full
#' permutation_test_tfce() (serial internally) in its own parallel worker, so
#' several tracts run at once. Use this INSTEAD OF `permutation_test_tfce_parallel()`
#' when you have many tracts and want to parallelize across them rather than
#' within one tract's permutation loop -- combining both levels of
#' parallelism at once causes worker oversubscription and is not supported
#' here on purpose.
#'
#' @param n_workers Number of tracts to run simultaneously. With more tracts
#'   than workers, `future` queues the rest automatically as workers free up
#'   -- you don't need n_workers >= length(tracts).
#' @param checkpoint_dir Optional directory. If set, each tract's result is
#'   saved to its own .rds file there as soon as that tract's worker
#'   finishes (this is the earliest point saving is actually possible --
#'   `future_lapply()` itself only returns once every tract is done, so
#'   per-tract saving has to happen inside the worker, not after the call
#'   returns). On a rerun with the same `checkpoint_dir`, any tract whose
#'   file already exists is loaded from disk and skipped entirely rather
#'   than recomputed -- so an interrupted batch resumes with only the
#'   unfinished tracts actually rerun. Tract names are sanitized into safe
#'   filenames (non-alphanumeric characters replaced with "_").
#' @param force_rerun If TRUE, ignores existing checkpoint files and reruns
#'   every tract (overwriting their checkpoints). Default FALSE.
#' @param ... Forwarded to `permutation_test_tfce()` for every tract
#'   (n_permutations, subject_col, family_col, E, H, alpha, random_state, etc).
#'   `verbose` is forced to FALSE internally since per-permutation progress
#'   messages from several simultaneous workers interleave unreadably --
#'   use `progress_updates = TRUE` (below) for cross-tract progress instead.
#' @param progress_updates If TRUE (default), prints a line as each tract
#'   finishes, in whatever order they complete (not necessarily the order
#'   given in `tracts`).
#' @return Same structure as `run_tfce_pipeline_multi_tract()`: list(results, summary).
run_tfce_pipeline_multi_tract_parallel <- function(data, tracts, fixed_formula,
                                                    var_of_interest,
                                                    tract_col = "tractID",
                                                    n_workers = 8,
                                                    checkpoint_dir = NULL,
                                                    force_rerun = FALSE,
                                                    progress_updates = TRUE,
                                                    ...) {
  library(future)
  library(future.apply)

  old_omp <- Sys.getenv("OMP_NUM_THREADS", unset = NA)
  old_veclib <- Sys.getenv("VECLIB_MAXIMUM_THREADS", unset = NA)
  Sys.setenv(OMP_NUM_THREADS = "1", VECLIB_MAXIMUM_THREADS = "1")

  old_plan <- plan()
  plan(multisession, workers = n_workers)
  on.exit({
    plan(old_plan)
    if (!is.na(old_omp)) Sys.setenv(OMP_NUM_THREADS = old_omp)
    if (!is.na(old_veclib)) Sys.setenv(VECLIB_MAXIMUM_THREADS = old_veclib)
  }, add = TRUE)

  if (!is.null(checkpoint_dir) && !dir.exists(checkpoint_dir)) {
    dir.create(checkpoint_dir, recursive = TRUE)
  }
  safe_name <- function(tr) gsub("[^A-Za-z0-9_-]", "_", tr)
  checkpoint_file_for <- function(tr) file.path(checkpoint_dir, paste0(safe_name(tr), ".rds"))

  dots <- list(...)
  dots$verbose <- FALSE  # force off -- see docstring

  tract_dfs <- lapply(tracts, function(tr) data[data[[tract_col]] == tr, ])
  names(tract_dfs) <- tracts

  valid_tracts <- tracts[vapply(tract_dfs, nrow, integer(1)) > 0]
  skipped <- setdiff(tracts, valid_tracts)
  if (length(skipped) > 0) {
    warning(sprintf("Tract(s) with no rows in `data`, skipped: %s", paste(skipped, collapse = ", ")))
  }

  # split into tracts already checkpointed (load, don't recompute) vs. tracts
  # that still need to run
  results_list <- setNames(vector("list", length(valid_tracts)), valid_tracts)
  to_run <- valid_tracts

  if (!is.null(checkpoint_dir) && !force_rerun) {
    already_done <- valid_tracts[file.exists(vapply(valid_tracts, checkpoint_file_for, character(1)))]
    for (tr in already_done) {
      results_list[[tr]] <- readRDS(checkpoint_file_for(tr))
      if (progress_updates) cat(sprintf("  [from checkpoint] %s\n", tr))
    }
    to_run <- setdiff(valid_tracts, already_done)
  }

  if (progress_updates && length(to_run) > 0) {
    cat(sprintf("Running %d tract(s) across up to %d parallel workers (%d loaded from checkpoint)...\n",
                length(to_run), n_workers, length(valid_tracts) - length(to_run)))
  }

  if (length(to_run) > 0) {
    new_results <- future_lapply(to_run, function(tr) {
      res <- tryCatch(
        do.call(permutation_test_tfce, c(
          list(df = tract_dfs[[tr]], fixed_formula = fixed_formula,
               var_of_interest = var_of_interest),
          dots
        )),
        error = function(e) list(.error = conditionMessage(e))
      )
      # save as soon as THIS worker's tract is done -- see docstring for why
      # this has to happen here rather than after future_lapply() returns
      if (!is.null(checkpoint_dir) && is.null(res$.error)) {
        saveRDS(res, checkpoint_file_for(tr))
      }
      res
    }, future.seed = TRUE, future.packages = c("lme4", "dplyr"))
    names(new_results) <- to_run

    for (tr in to_run) results_list[[tr]] <- new_results[[tr]]
  }

  results <- vector("list", length(tracts)); names(results) <- tracts
  summary_rows <- vector("list", length(tracts))

  for (tr in valid_tracts) {
    res <- results_list[[tr]]
    if (is.null(res) || !is.null(res$.error)) {
      warning(sprintf("Tract '%s' failed: %s", tr, if (!is.null(res$.error)) res$.error else "unknown error"))
      if (progress_updates) cat(sprintf("  [FAILED] %s\n", tr))
      next
    }
    results[[tr]] <- res
    summary_rows[[tr]] <- data.frame(
      tract = tr,
      n_significant_nodes = sum(res$sig_nodes, na.rm = TRUE),
      min_pvalue = suppressWarnings(min(res$node_pvalues, na.rm = TRUE)),
      n_na_nodes_observed = res$n_na_nodes_observed
    )
    if (progress_updates && tr %in% to_run) cat(sprintf("  [done] %s\n", tr))
  }

  list(results = results, summary = bind_rows(summary_rows))
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
