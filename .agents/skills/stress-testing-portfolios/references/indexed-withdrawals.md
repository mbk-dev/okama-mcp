# Indexed withdrawal comparisons

Use this workflow for nominal preservation, real preservation and finite-horizon
spending comparisons. State the objective before calculating a withdrawal.

1. Resolve the actual common history, including inflation and currency conversion.
   For a forward-model exercise, use the maximum available common period unless
   the user specifies another window. Pin those resolved dates for reproducibility.
   A dated historical first-passage exercise may deliberately use a fixed window.
2. Specify whether the terminal target is the initial nominal amount,
   inflation-adjusted purchasing power, or no reserve with survival through the
   spending horizon. State the model success probability; an initial withdrawal
   amount without these assumptions is not a unique answer.
3. Compare available monthly-return distributions on historical fit, left-tail
   errors and held-out forecasts where feasible. Separate evidence about monthly
   returns from claims about long-horizon withdrawal accuracy. Fitted-sample KS
   p-values with estimated parameters are not calibrated significance tests.
4. Keep historical dates, parameters, seed, scenario count, inflation convention,
   spending timing and horizon identical across objective comparisons. Check the
   actual sampled paths if configuration can change their order or length.
5. Distinguish `optimize_students_df(var_level=20)`, which calibrates df to VaR
   and CVaR in the lower 20% monthly-return tail while holding location and scale
   fixed, from `percentile=20` for the terminal/survival criterion. Setting the
   latter alone does not optimize df or prove a distribution is appropriate.
6. For `indexation="inflation"`, read the resolved rate and compounding convention.
   In the checked okama implementation this is historical inflation CAGR,
   compounded into each payment period, not a stochastic future inflation path.
   Use explicit dated flows for an annual step schedule when that is intended.
7. Use `maintain_balance_fv` for nominal preservation and `maintain_balance_pv`
   for real preservation; confirm the discount rate used for PV. For survival,
   inspect the installed library's horizon guard. Extending a simulation to make
   a solver accept the target is not verification of the exact spending horizon.
8. Verify the candidate on the requested horizon and all scheduled payments.
   Count paths that never exhaust capital, and apply any terminal reserve test.
   Check the final rounded teaching answer too. Survival-time quantiles and
   numerical tolerances may admit a candidate just below the desired success rate.
9. Report the initial monthly amount, indexing rate, actual history, distribution,
   calibration, seed, horizon and probability. Describe terminal real preservation
   as a probabilistic objective, not full protection or a ban on interim drawdowns.
   Preserve evidence outside disposable scratch space before retiring the task.

The [SFA teaching snapshot](../../../../docs/research/sfa-course/README.md) records
an example, including why nominal preservation and depletion can give similar
amounts while real preservation yields a much larger difference. Its numbers are
historical, not general defaults for other portfolios.
