from datetime import timedelta

from airflow.models import DAG
from airflow.utils.dates import days_ago
from airflow.utils.trigger_rule import TriggerRule
from airflow.utils.log.logging_mixin import LoggingMixin

#from kaapana.operators.LocalMinioOperator import LocalMinioOperator
# --> TODO: needs option to overwrite name
#from airflow.operators.python_operator import BranchPythonOperator (as: KaapanaBranchPythonBaseOperator)
# --> TODO: Needs to be included in Kaapana Base
from kaapana.operators.LocalWorkflowCleanerOperator import LocalWorkflowCleanerOperator

from federated_training.EntrypointOperator import EntrypointOperator
from federated_training.TriggerRemoteWorkersOperator import TriggerRemoteWorkersOperator
from federated_training.AwaitingModelsOperator import AwaitingModelsOperator
from federated_training.TriggerMyselfOperator import TriggerMyselfOperator

from federated_training.experiments.ExperimentChestXrayOperator import ExperimentChestXrayOperator


log = LoggingMixin().log

args = {
    'ui_visible': False,
    'owner': 'kaapana',
    'start_date': days_ago(0),
    'retries': 2,
    'retry_delay': timedelta(seconds=30),
}

dag = DAG(
    dag_id='federated-experiment-chest-xray',
    default_args=args,
    schedule_interval=None,
    concurrency=10,
    max_active_runs=5
)

def _choose_branch(ti, **kwargs):
    successor = ti.xcom_pull(key='successor', task_ids='entrypoint')
    print('##### Successor given be previous task: {}'.format(successor))
    return successor

branching = KaapanaBranchPythonBaseOperator(
    dag=dag,
    name='branching',
    task_id='branching',
    python_callable=_choose_branch,
    provide_context=True
)

entrypoint = EntrypointOperator(
    dag=dag,
    fed_round=0,
    init_model=True
)

init_model = ExperimentChestXrayOperator(
    dag=dag,
    name='init-model',
    init_model=True,
    learning_rate=0.1
)

clear_minio = LocalMinioOperator(
    dag=dag,
    name='clear-minio',
    action='remove',
    bucket_name='federated-exp-chest-xray',
    action_operator_dirs=['cache', 'model']
)

model_to_minio = LocalMinioOperator(
    dag=dag,
    name='model-to-minio',
    action='put',
    bucket_name='federated-exp-chest-xray',
    action_operator_dirs=['model', 'checkpoints'],
    operator_out_dir='model',
    trigger_rule=TriggerRule.ONE_SUCCESS
)

trigger_remote_dags = TriggerRemoteWorkersOperator(
    dag=dag,
    dag_name='federated-training-chest-xray',
    scheduler=None,
    worker=None,
    procedure=None,
    participants=None,
    use_cuda=True,
    local_testing=True,
    epochs_on_worker=1,
    bucket_name='federated-exp-chest-xray'
)

wait_for_models = AwaitingModelsOperator(
    dag=dag,
    worker=None,
    procedure=None,
    participants=None,
    bucket_name='federated-exp-chest-xray'
)

pull_models_from_minio =LocalMinioOperator(
    dag=dag,
    action='get',
    bucket_name='federated-exp-chest-xray',
    action_operator_dirs=['cache'],
    operator_out_dir='cache'
)

process_models = ExperimentChestXrayOperator(
    dag=dag,
    name='process-models',
    procedure=None,
    init_model=False,
    save_checkpoints=True
)

trigger_myself = TriggerMyselfOperator(
    dag=dag,
    worker=None,
    procedure=None,
    participants=None,
    action_dirs=['model', 'checkpoints'])

final_model_to_minio = LocalMinioOperator(
    dag=dag,
    name='final-model-to-minio',
    action='put',
    bucket_name='federated-exp-chest-xray',
    action_operator_dirs=['model', 'checkpoints'],
    operator_out_dir='model'
)

cleanup = LocalWorkflowCleanerOperator(dag=dag, clean_workflow_dir=True)

entrypoint >> branching >> [init_model, clear_minio, final_model_to_minio]
init_model >> model_to_minio >> trigger_remote_dags >> wait_for_models >> pull_models_from_minio >> process_models >> trigger_myself >> cleanup
clear_minio >> model_to_minio >> trigger_remote_dags >> wait_for_models >> pull_models_from_minio >> process_models >> trigger_myself >> cleanup