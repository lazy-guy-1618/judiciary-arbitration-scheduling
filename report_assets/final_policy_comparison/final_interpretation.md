# Final Unified Comparison Interpretation
This table evaluates all selected schedules under the same three objective metrics:
- Delay mean: higher is better.
- Fairness score: higher is better.
- Complexity mean: lower is better.

## Extremes
- Highest delay score: Bi-objective: delay-complexity / lambda_0.00 with delay_mean=1000.375, fairness_score=0.770, complexity_mean=23.525.
- Highest fairness score: Bi-objective: delay-fairness / lambda_1.00 with delay_mean=625.210, fairness_score=0.978, complexity_mean=19.050.
- Lowest complexity: Bi-objective: delay-complexity / lambda_1.00 with delay_mean=517.025, fairness_score=0.778, complexity_mean=1.450.

## Main takeaway
Single-objective policies occupy extreme regions of the objective space: delay-oriented policies are strong on delay but weaker on representation, SJF-like policies reduce complexity but lose delay priority, and round-robin improves representation but sacrifices delay. Bi-objective and multi-objective schedules provide intermediate, controllable trade-off points between delay, fairness, and complexity.
