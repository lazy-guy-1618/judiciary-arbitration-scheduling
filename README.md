# Judicial Case Scheduling in India

This repository contains the implementation for my MTP thesis project, **“Judicial Case Scheduling in India”**, submitted as part of the Dual Degree (B.Tech & M.Tech Integrated) programme in the Department of Computer Science and Engineering, IIT Kharagpur.

**Author:** Mihir Mallick  
**Roll Number:** 21CS30031  
**Supervisor:** Dr. Abhijnan Chakraborty  
**Institute:** Indian Institute of Technology Kharagpur  

The thesis studies judicial case listing as a scheduling problem. It focuses on arbitration-related matters from the **Appellate Side of the Calcutta High Court**, using the case types:

- `FMAT`
- `AOCOM`
- `ADCOM`

The project builds a feature-based scheduling dataset and evaluates single-objective, bi-objective, and multi-objective scheduling policies for prioritising cases under limited listing capacity.

---

## 1. Project Overview

Courts operate under limited daily listing capacity. Every working day, only a subset of pending matters can be listed or effectively prioritised. This creates an operational scheduling problem: which cases should be selected so that old, inactive, and repeatedly listed matters are not ignored, while smaller case categories are not starved?

This project models each case using scheduling-relevant features such as:

- case age,
- gap since last activity,
- hearing-history count,
- order count,
- case type.

Using these features, the project compares several scheduling policies and studies trade-offs between:

- delay reduction,
- inactivity reduction,
- case-type fairness,
- complexity control,
- backlog movement.

The implementation is a research prototype and is not intended to replace judicial discretion or official court-listing processes.

---

## 2. Repository Structure

```text
.
├── config/
│   └── courts.yaml
│
├── src/
│   ├── scrape_chc_appellate_arbitration_pdfs.py
│   ├── parse_appellate_arbitration_causelists.py
│   ├── scrape_chc_scheduling_inputs.py
│   ├── parse_chc_scheduling_inputs.py
│   ├── parse_raw_to_tables.py
│   ├── scrape_chc_order_texts.py
│   ├── parse_chc_order_texts.py
│   ├── CHC_scheduling_scraper_README.md
│   └── APP_SIDE_ARBITRATION_CAUSELIST_PIPELINE.md
│
├── sched/
│   ├── run_scheduling_simulation.py
│   ├── run_weight_sensitivity.py
│   ├── visualize_scheduling_results.py
│   ├── visualize_weight_sensitivity.py
│   └── visualize_weight_sensitivity_clean.py
│
├── biobj/
│   ├── run_biobjective_scheduling.py
│   ├── run_biobjective_delay_complexity.py
│   ├── visualize_biobjective_results.py
│   ├── visualize_biobjective_results_clean.py
│   ├── visualize_biobjective_capacity_compare.py
│   └── visualize_delay_complexity.py
│
├── multiobj/
│   ├── run_multiobjective_scheduling.py
│   ├── visualize_multiobjective_results.py
│   ├── visualize_multiobjective_results_clean.py
│   └── visualize_multiobjective_capacity_compare.py
│
├── report_assets/
│   └── figures/
│
├── requirements.txt
└── README.md
````

The `output/` directory is used for generated data, parsed tables, intermediate features, and experiment results. It is intentionally ignored from Git to keep the repository lightweight.

---

## 3. Installation

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

If needed, install the core dependencies manually:

```bash
pip install pandas numpy matplotlib requests beautifulsoup4 pymupdf pypdf pyyaml
```

---

## 4. Data Assumptions

The expected raw case-status data layout is:

```text
output/raw/
├── 2024/
│   ├── FMAT/
│   ├── AOCOM/
│   └── ADCOM/
├── 2025/
│   ├── FMAT/
│   ├── AOCOM/
│   └── ADCOM/
└── 2026/
    ├── FMAT/
    ├── AOCOM/
    └── ADCOM/
```

Each case-type folder contains JSONL files for pending and disposed cases.

The main final scheduling dataset used by experiments is:

```text
output/features/scheduling_case_dataset.csv
```

If this file is already present, the scheduling experiments can be run directly. If not, generate it through the parsing and feature-building steps below.

---

## 5. Pipeline

### 5.1 Parse raw case-status data

```bash
python src/parse_raw_to_tables.py \
  --input-dir output/raw \
  --out-dir output/tables
```

This produces structured case tables such as:

```text
output/tables/cases.csv
output/tables/case_history.csv
output/tables/acts.csv
output/tables/advocates.csv
output/tables/document_details.csv
output/tables/ia_details.csv
output/tables/objection.csv
output/tables/orders.csv
output/tables/subordinate_court_information.csv
```

---

### 5.2 Extract order metadata

```bash
python scrape_chc_order_texts_v2.py \
  --case-jsonl-dir output/raw \
  --out-dir output/order_raw \
  --case-types FMAT AOCOM ADCOM \
  --years 2024 2025 2026 \
  --no-download
```

This creates:

```text
output/order_raw/order_manifest.csv
output/order_raw/order_manifest.jsonl
```

Direct PDF download may not always work because many order links are session-backed. The scheduling experiments use extracted order metadata such as order count and order dates.

---

### 5.3 Build scheduling dataset

The final dataset combines:

* case metadata,
* hearing history,
* order metadata,
* case age,
* inactivity gap,
* hearing count,
* order count,
* case type.

Expected output:

```text
output/features/scheduling_case_dataset.csv
```

---

## 6. Running Experiments

### 6.1 Single-objective scheduling

Run:

```bash
python sched/run_scheduling_simulation.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/scheduling_results \
  --capacity 20 \
  --days 10
```

Generate plots:

```bash
python sched/visualize_scheduling_results.py \
  --results-dir output/scheduling_results
```

Policies compared:

| Policy                  | Meaning                                             |
| ----------------------- | --------------------------------------------------- |
| `fcfs_oldest_first`     | Oldest cases first                                  |
| `gap_first`             | Longest inactivity gap first                        |
| `weighted_age_gap`      | Weighted age-gap-hearing priority                   |
| `balanced_priority`     | Weighted priority with mild complexity penalty      |
| `sjf_proxy`             | Simpler cases first using hearing/order count proxy |
| `round_robin_case_type` | Rotates across FMAT, AOCOM, ADCOM                   |

---

### 6.2 Coefficient sensitivity

Run:

```bash
python sched/run_weight_sensitivity.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/weight_sensitivity_cap20 \
  --capacity 20
```

Generate clean plots:

```bash
python sched/visualize_weight_sensitivity_clean.py \
  --results-dir output/weight_sensitivity_cap20
```

The weighted score is:

```text
Score(c) = alpha * age + beta * inactivity_gap + gamma * hearing_count - delta * order_count
```

This experiment studies whether changing the coefficients changes the selected case set.

---

### 6.3 Bi-objective scheduling: delay vs fairness

Run:

```bash
python biobj/run_biobjective_scheduling.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/biobjective_results_cap20 \
  --capacity 20
```

Generate plots:

```bash
python biobj/visualize_biobjective_results_clean.py \
  --results-dir output/biobjective_results_cap20
```

This experiment studies the trade-off between:

* selecting old/high-delay cases,
* maintaining representation across FMAT, AOCOM, and ADCOM.

---

### 6.4 Bi-objective scheduling: delay vs complexity

Run:

```bash
python biobj/run_biobjective_delay_complexity.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/biobjective_delay_complexity_cap20 \
  --capacity 20
```

Generate plots:

```bash
python biobj/visualize_delay_complexity.py \
  --results-dir output/biobjective_delay_complexity_cap20
```

This experiment studies the trade-off between:

* delay-priority selection,
* selecting less complex cases.

Complexity is approximated using hearing-history count and order count.

---

### 6.5 Multi-objective scheduling

Run:

```bash
python multiobj/run_multiobjective_scheduling.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/multiobjective_results_cap20 \
  --capacity 20
```

Generate clean plots:

```bash
python multiobj/visualize_multiobjective_results_clean.py \
  --results-dir output/multiobjective_results_cap20
```

The multi-objective experiment combines:

* delay priority,
* case-type fairness,
* complexity control.

---

### 6.6 Capacity sensitivity

Run multi-objective experiments at different capacities:

```bash
python multiobj/run_multiobjective_scheduling.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/multiobjective_results_cap10 \
  --capacity 10

python multiobj/run_multiobjective_scheduling.py \
  --input output/features/scheduling_case_dataset.csv \
  --out-dir output/multiobjective_results_cap30 \
  --capacity 30
```

Generate comparison plot:

```bash
python multiobj/visualize_multiobjective_capacity_compare.py
```

---

## 7. Important Outputs

Single-objective outputs:

```text
output/scheduling_results/policy_day1_summary.csv
output/scheduling_results/multi_day_metrics.csv
output/scheduling_results/plots/
```

Coefficient sensitivity outputs:

```text
output/weight_sensitivity_cap20/weight_sensitivity_summary.csv
output/weight_sensitivity_cap20/plots_clean/
```

Bi-objective outputs:

```text
output/biobjective_results_cap20/biobjective_summary.csv
output/biobjective_results_cap20/plots_clean/
output/biobjective_delay_complexity_cap20/delay_complexity_summary.csv
```

Multi-objective outputs:

```text
output/multiobjective_results_cap20/multiobjective_summary.csv
output/multiobjective_results_cap20/plots_clean/
output/multiobjective_capacity_compare/
```

Selected final figures may be copied into:

```text
report_assets/figures/
```

---

## 8. Main Findings

The experiments show the following broad conclusions:

1. **Delay-oriented policies** such as oldest-first, gap-first, and weighted age-gap scheduling are effective at surfacing old and inactive matters.

2. **Case age and inactivity gap are related but not identical.** Oldest-first selects the oldest cases, while gap-first selects cases waiting longest since last activity.

3. **Pure delay-priority scheduling can underrepresent smaller case categories.** In the experiments, ADCOM matters do not appear in several delay-heavy top-20 schedules.

4. **Round-robin improves case-type representation** across FMAT, AOCOM, and ADCOM, but lowers average selected age.

5. **SJF-like scheduling selects simpler matters**, but leaves more old backlog behind.

6. **Coefficient sensitivity shows stability.** Moderate changes in age, gap, hearing, and order-count weights often select similar top cases because old cases also tend to have long inactivity gaps.

7. **Bi-objective scheduling exposes trade-offs.** Fairness must be weighted sufficiently before ADCOM appears in the selected schedule.

8. **Multi-objective scheduling is more realistic.** Delay reduction, case-type fairness, and complexity control must be considered together.

---

## 9. Limitations

This project is a first-stage research prototype. Current limitations include:

* selection-level scheduling only,
* simplified fixed listing capacity,
* no full judge/bench assignment model,
* no advocate conflict modelling,
* no exact hearing-duration prediction,
* no stochastic simulation of adjournment, disposal, or not-reached outcomes,
* order text not always directly downloadable due to session-backed court links,
* case-type fairness is limited to FMAT, AOCOM, and ADCOM representation.

---

## 10. Future Work

Future extensions include:

* richer stochastic court-day simulation,
* order-text outcome classification,
* judge and bench availability constraints,
* advocate conflict modelling,
* hearing-duration and disposal-probability prediction,
* genetic algorithms,
* NSGA-II for Pareto-front search,
* simulated annealing or tabu search,
* reinforcement learning after building a credible simulator.

---

## 11. Disclaimer

This repository is for academic and research purposes only. It does not provide legal advice and is not intended to represent or replace official court scheduling practices.

