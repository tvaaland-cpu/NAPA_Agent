# NAPA Agent

Python monitoring agent for Napatech A/S (NAPA.OL), focused on shareholder changes, company updates, and rumor monitoring.

## Quick start

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -e .`
3. `cp .env.example .env` and update SMTP credentials
4. Run scheduler: `python -m napa_agent.scripts.run` or `python scripts/run.py`
5. Run tests: `pytest`
