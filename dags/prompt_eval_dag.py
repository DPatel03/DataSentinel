"""
Airflow DAG — run eval suite on prompt version changes.

Mount this file into Airflow's dags folder:
  docker compose -f docker-compose.airflow.yml up -d
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "datasentinel",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="datasentinel_prompt_eval",
    default_args=default_args,
    description="Run DataSentinel eval harness after prompt changes",
    schedule=None,  # triggered manually or via prompt registry webhook
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["datasentinel", "eval", "prompts"],
) as dag:
    generate_dataset = BashOperator(
        task_id="generate_dataset",
        bash_command="cd /opt/datasentinel && python eval/dataset/generate_dataset.py",
    )

    run_eval = BashOperator(
        task_id="run_eval_harness",
        bash_command=(
            "cd /opt/datasentinel && "
            "PYTHONPATH=. python eval/runner.py --json "
            "--prompt-version {{ dag_run.conf.get('prompt_version', 'latest') }}"
        ),
    )

    run_tests = BashOperator(
        task_id="run_eval_tests",
        bash_command="cd /opt/datasentinel && PYTHONPATH=. pytest tests/test_eval.py -q",
    )

    generate_dataset >> run_eval >> run_tests
