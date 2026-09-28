#' GAMM-based along-tract analysis (varying-coefficient smooth + simultaneous CI
#' cluster detection), looped over multiple tracts.
#'
#' Companion to tfce_tractometry.R -- same multi-tract-wrapper design, but for
#' the GAMM/mgcv approach: fits
#'   outcome ~ s(nodeID, by = var_of_interest) + s(nodeID) + covariates +
#'             s(subjectID, bs="re") + s(familyID, bs="re")
#' per tract, builds a simultaneous confidence band for the varying-coefficient
#' smooth via posterior simulation (working around gratia::confint.gam()'s
#' inability to handle continuous by-variable smooths), and identifies the
#' contiguous node ranges where that band excludes zero.
#'
#' Run source("gamm_tractometry.R") once in your .Rmd, then call
#' run_gamm_pipeline_multi_tract().

library(mgcv)
library(gratia)
library(dplyr)
library(tidyr)
library(ggplot2)

# ---------------------------------------------------------------------------
# 1. Build a simultaneous + pointwise CI band for a varying-coefficient smooth
# ---------------------------------------------------------------------------

#' See prior discussion: gratia::confint.gam() fails on smooths with a
#' continuous `by` variable (calls an internal helper that assumes factor
#' levels). This builds both bands manually from smooth_estimates() +
#' smooth_samples(), which both work fine on continuous-by smooths.
#'
#' @param model A fitted gam()/bam() object.
#' @param select The smooth's gratia select string, e.g. "s(nodeID):FSIQ2".
#' @param data An evaluation grid data frame -- one row per node, with every
#'   model variable present (fixed at a reference value for anything other
#'   than the focal smooth's variables). See `build_eval_grid()` below.
#' @param n_draws Posterior draws for the simultaneous band (1000+ recommended).
#' @param seed Optional seed for reproducibility.
#' @param level Confidence level (0.95 default).
#' @return `data` joined with .estimate, .se, and both CI bands.
plot_by_smooth_ci <- function(model, select, data, n_draws = 1000,
                               seed = NULL, level = 0.95) {
  sm <- smooth_estimates(model, select = select, data = data) %>% arrange(nodeID)
  draws <- smooth_samples(model, select = select, n = n_draws, data = data, seed = seed)

  draws_wide <- draws %>%
    select(nodeID, .draw, .value) %>%
    pivot_wider(names_from = .draw, values_from = .value) %>%
    arrange(nodeID)
  stopifnot(all(draws_wide$nodeID == sm$nodeID))

  draw_mat <- as.matrix(draws_wide[, -1])
  z_mat <- sweep(draw_mat - sm$.estimate, 1, sm$.se, "/")
  max_abs_z <- apply(z_mat, 2, function(col) max(abs(col)))
  crit_simultaneous <- quantile(max_abs_z, level)
  z_pointwise <- qnorm(1 - (1 - level) / 2)

  sm$lower_simultaneous <- sm$.estimate - crit_simultaneous * sm$.se
  sm$upper_simultaneous <- sm$.estimate + crit_simultaneous * sm$.se
  sm$lower_pointwise    <- sm$.estimate - z_pointwise * sm$.se
  sm$upper_pointwise    <- sm$.estimate + z_pointwise * sm$.se
  sm
}


# ---------------------------------------------------------------------------
# 2. Find contiguous node ranges where the CI excludes zero
# ---------------------------------------------------------------------------

find_significant_clusters <- function(sm, lower_col = "lower_simultaneous",
                                       upper_col = "upper_simultaneous",
                                       node_col = "nodeID") {
  sm <- sm[order(sm[[node_col]]), ]
  sig <- (sm[[lower_col]] > 0) | (sm[[upper_col]] < 0)

  rl <- rle(sig)
  ends   <- cumsum(rl$lengths)
  starts <- ends - rl$lengths + 1
  sig_runs <- which(rl$values)

  if (length(sig_runs) == 0) {
    return(data.frame(start_node = numeric(0), end_node = numeric(0),
                       n_nodes = integer(0), direction = character(0)))
  }

  do.call(rbind, lapply(sig_runs, function(i) {
    idx <- starts[i]:ends[i]
    data.frame(
      start_node = sm[[node_col]][starts[i]],
      end_node   = sm[[node_col]][ends[i]],
      n_nodes    = length(idx),
      direction  = ifelse(mean(sm$.estimate[idx]) > 0, "positive", "negative")
    )
  }))
}


# ---------------------------------------------------------------------------
# 3. Build an evaluation grid automatically from the fitted data
# ---------------------------------------------------------------------------

#' Construct the one-row-per-node evaluation grid needed by
#' smooth_estimates()/smooth_samples(): a sweep over node position with the
#' by-variable fixed at 1 (gratia's convention for continuous by-smooths --
#' the smooth then represents the per-unit-of-var_of_interest effect), and
#' every other model variable fixed at a reference value (mean for numeric,
#' first observed level for factor) since gam()'s model.frame construction
#' needs them present even though they don't affect this particular smooth.
build_eval_grid <- function(data, node_col, var_of_interest, covariates,
                             subject_col, family_col, n_nodes) {
  grid <- data.frame(node = 0:(n_nodes - 1))
  names(grid) <- node_col
  grid[[var_of_interest]] <- 1

  for (v in covariates) {
    if (is.numeric(data[[v]])) {
      grid[[v]] <- mean(data[[v]], na.rm = TRUE)
    } else {
      # factor/character covariate -- fix at first observed level
      grid[[v]] <- data[[v]][1]
    }
  }

  grid[[subject_col]] <- factor(data[[subject_col]][1], levels = levels(data[[subject_col]]))
  grid[[family_col]]  <- factor(data[[family_col]][1],  levels = levels(data[[family_col]]))
  grid
}


# ---------------------------------------------------------------------------
# 4. Single-tract GAMM fit + CI + cluster detection
# ---------------------------------------------------------------------------

#' Fit the varying-coefficient GAMM for one tract's data and return the
#' model, the CI band table, and the significant-cluster table.
#'
#' @param df Data for ONE tract (one row per subject per node).
#' @param outcome Outcome variable name, e.g. "dti_fa".
#' @param var_of_interest The continuous by-variable, e.g. "FSIQ2".
#' @param covariates Character vector of other fixed-effect covariates,
#'   e.g. c("mri_age", "gadays", "bw", "mean_fd", "female").
#' @param subject_col,family_col,node_col Column names.
#' @param n_nodes Number of nodes per tract.
#' @param n_draws,seed,level Passed to `plot_by_smooth_ci()`.
#' @param method Passed to gam() (default "REML").
#' @return list(model, sm, clusters)
run_gamm_by_smooth <- function(df, outcome, var_of_interest, covariates,
                                subject_col = "subjectID", family_col = "familyID",
                                node_col = "nodeID", n_nodes = 100,
                                n_draws = 1000, seed = NULL, level = 0.95,
                                method = "REML") {
  fixed_part <- paste(covariates, collapse = " + ")
  formula_str <- sprintf(
    "%s ~ s(%s, by = %s) + s(%s) + %s + s(%s, bs = 're') + s(%s, bs = 're')",
    outcome, node_col, var_of_interest, node_col, fixed_part, subject_col, family_col
  )

  model <- gam(as.formula(formula_str), data = df, method = method)

  select_str <- sprintf("s(%s):%s", node_col, var_of_interest)
  eval_grid <- build_eval_grid(df, node_col, var_of_interest, covariates,
                                subject_col, family_col, n_nodes)

  sm <- plot_by_smooth_ci(model, select_str, eval_grid,
                           n_draws = n_draws, seed = seed, level = level)
  clusters <- find_significant_clusters(sm)

  list(model = model, sm = sm, clusters = clusters)
}


# ---------------------------------------------------------------------------
# 5. Multi-tract wrapper
# ---------------------------------------------------------------------------

#' Loop `run_gamm_by_smooth()` over multiple tracts from one long-format
#' dataframe, mirroring run_tfce_pipeline_multi_tract()'s interface.
#'
#' @param data Long-format data covering ALL tracts (one row per subject per
#'   node per tract).
#' @param tracts Character vector of tract names, as they appear in
#'   `data[[tract_col]]`.
#' @param outcome,var_of_interest,covariates,subject_col,family_col,node_col,
#'   n_nodes,n_draws,seed,level,method As in `run_gamm_by_smooth()`, applied
#'   identically to every tract.
#' @param tract_col Column identifying tract per row.
#' @return list(results = named list of run_gamm_by_smooth() output per tract,
#'   summary = one-row-per-tract data frame of cluster counts/extents)
run_gamm_pipeline_multi_tract <- function(data, tracts, outcome, var_of_interest,
                                           covariates, tract_col = "tractID",
                                           subject_col = "subjectID",
                                           family_col = "familyID",
                                           node_col = "nodeID", n_nodes = 100,
                                           n_draws = 1000, seed = NULL,
                                           level = 0.95, method = "REML") {
  results <- vector("list", length(tracts))
  names(results) <- tracts
  summary_rows <- vector("list", length(tracts))

  for (tr in tracts) {
    cat("\n=== Running GAMM for tract:", tr, "===\n")
    tract_df <- data[data[[tract_col]] == tr, ]

    if (nrow(tract_df) == 0) {
      warning(sprintf("Tract '%s' has no rows in `data` -- skipping.", tr))
      next
    }

    res <- tryCatch(
      run_gamm_by_smooth(
        tract_df, outcome = outcome, var_of_interest = var_of_interest,
        covariates = covariates, subject_col = subject_col,
        family_col = family_col, node_col = node_col, n_nodes = n_nodes,
        n_draws = n_draws, seed = seed, level = level, method = method
      ),
      error = function(e) {
        warning(sprintf("Tract '%s' failed: %s", tr, conditionMessage(e)))
        NULL
      }
    )
    if (is.null(res)) next
    results[[tr]] <- res

    n_clusters <- nrow(res$clusters)
    total_sig_nodes <- if (n_clusters > 0) sum(res$clusters$n_nodes) else 0

    summary_rows[[tr]] <- data.frame(
      tract = tr,
      n_significant_clusters = n_clusters,
      total_significant_nodes = total_sig_nodes,
      largest_cluster_nodes = if (n_clusters > 0) max(res$clusters$n_nodes) else 0
    )
  }

  summary_df <- bind_rows(summary_rows)
  list(results = results, summary = summary_df)
}


# ---------------------------------------------------------------------------
# 6. Plotting for one tract's result
# ---------------------------------------------------------------------------

plot_gamm_result <- function(res, tract_name = "", var_of_interest = "var of interest") {
  sm <- res$sm
  ggplot(sm, aes(x = nodeID, y = .estimate)) +
    geom_ribbon(aes(ymin = lower_simultaneous, ymax = upper_simultaneous),
                fill = "steelblue", alpha = 0.2) +
    geom_ribbon(aes(ymin = lower_pointwise, ymax = upper_pointwise),
                fill = "steelblue", alpha = 0.35) +
    geom_line(color = "steelblue4", linewidth = 1) +
    geom_hline(yintercept = 0, linetype = "dashed", color = "gray40") +
    labs(x = "Node position", y = paste("Effect of", var_of_interest),
         title = paste0(tract_name, ": varying-coefficient smooth along tract"),
         subtitle = "Dark band = pointwise 95% CI; light band = simultaneous 95% CI") +
    theme_minimal()
}
