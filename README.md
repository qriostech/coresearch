<p align="center">
  <img src="coresearch-front/assets/coresearch.svg" alt="co.research" width="250">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-green.svg?style=flat-square" alt="Python"></a>
  <a href="https://docs.docker.com/compose/"><img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg?style=flat-square&logo=docker&logoColor=white" alt="Docker"></a>
  <a href="https://github.com/FilipAlexander/coresearch/issues"><img src="https://img.shields.io/badge/Contributions-Welcome-orange.svg?style=flat-square" alt="Contributions Welcome"></a>
</p>

**co.research** is an _open-source platform_ designed to enhance collaboration between human researchers and artificial intelligence.

The workflow revolves around optimization experiments. Each experiment is defined in a format similar to autoresearch and is referred to as a **seed**. From a seed, users can create **branches** — independent exploration paths. Within each branch, an agent with a distinct context and harness is initialized to iteratively evolve the codebase with the goal of improving the evaluation score. The user then oversees this multi-branch evolution, steering it toward greater efficiency and superior results.

## Quick Showcase
https://github.com/user-attachments/assets/d03f6075-7f74-4d97-a6d2-9f99d99b0d1b

## Installation

```bash
git clone {repo_url}
cd $directory
docker compose up
```

## Workflow
1. Modify your experiment to conform to coresearch [guidelines](https://github.com/qriostech/guidelines/blob/main/coresearch/guidelines/guidelines_v004.md) (try asking agent do it).
2. Visit http://127.0.0.1:5173 , new seed and add the repository details.
3. Create a branch or branches. Session will pop up in the left sidebar. (session is a terminal instance on a runner, right now sessions are created using tmux)
4. Go into the session. Invoke the agent (codex and claude are pre-installed) and tell him to start the experiment and explain what to optimize. Wait, have a coffee, read a paper.
5. Inspect metrics, visuals, diffs. 
6. When you like something fork it. It creates a new session where you have the opportunity to let the agent continue the experiment but tweak what are trying to achieve.
7. When something looks really good remember to test it out of sample if you are optimizing a problem where it is relevant. 
8. Push it to version control.

## Troubleshooting
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

