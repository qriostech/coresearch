<p align="center">
  <img src="coresearch-front/assets/coresearch.svg" alt="co.research" width="250">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=flat-square" alt="Apache 2.0 License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-green.svg?style=flat-square" alt="Python"></a>
  <a href="https://docs.docker.com/compose/"><img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg?style=flat-square&logo=docker&logoColor=white" alt="Docker"></a>
  <a href="https://github.com/qriostech/coresearch/issues"><img src="https://img.shields.io/badge/Contributions-Welcome-orange.svg?style=flat-square" alt="Contributions Welcome"></a>
</p>

Running a coding agent on an ML experiment usually means one agent, one terminal, one direction — and a lot of waiting.

co.research is an open-source platform that addresses this by running agents in parallel and bringing observability to the iteration process.
Define your experiment as a seed, then branch it and give each branch its own research direction — one tries XGBoost, another logistic regression, another expands the feature set. Each branch's agent iterates toward a better evaluation score while under your supervision. Code diffs, metrics, visual outputs, and other metadata stream into a clean UI as they come in.

Codex and Claude come pre-installed. Bring your own experiment, or start from the included example.

## Quick Showcase
https://github.com/user-attachments/assets/bb4982fd-7c59-4604-b015-1fd47e686bda

## Installation

```bash
git clone https://github.com/qriostech/coresearch.git
cd coresearch
docker compose up
```

## Workflow
1. Modify your experiment to conform to coresearch [guidelines](https://github.com/qriostech/guidelines/blob/main/coresearch/guidelines/guidelines_v004.md) (try asking agent do it). Alternatively use prepared [experiment](https://github.com/qriostech/cdchealth).
2. Visit http://127.0.0.1:5173 , click new seed and add the repository details. (You may use https://github.com/qriostech/diabetes to create seed to quickstart)
3. Create a branch or branches. Session will pop up in the left sidebar. (session is a terminal instance on a runner, right now sessions are created using tmux)
4. Go into the session. Invoke the agent (codex and claude are pre-installed) and tell him to start the experiment and explain what to optimize. Wait, have a coffee, read a paper.
5. Inspect metrics, visuals, diffs. 
6. When you like something fork it. It creates a new session where you have the opportunity to let the agent continue the experiment but tweak what are trying to achieve.
7. When something looks really good remember to test it out of sample if you are optimizing a problem where it is relevant. 
8. Push it to version control.

## Troubleshooting
The repository is very new and there is rapid developmnet. Sometimes full no chache rebuild might be needed.
```bash
docker compose down -v && docker compose build --no-cache && docker compose up -d
```

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Experiment** | A defined optimization run |
| **Evaluation** | Scoring mechanism for results |
| **Metric** | Quantitative measure of progress |
| **Visual** | Visual representation of results |
| **Hypothesis** | A proposed direction to explore |
| **Analysis** | Interpretation of experiment outcomes |
| **Seed** | Initial experiment definition |
| **Branch** | Independent exploration path |
| **Session** | A working period within a branch |
| **Iteration** | A single evolution step |

## Special Thanks

[@karpathy](https://github.com/karpathy)
[@coder](https://github.com/coder/ghostty-web)
[@mitchellh](https://github.com/mitchellh)

