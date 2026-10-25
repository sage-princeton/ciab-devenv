"""Bounded AgentRQ tasks; controller administrator credentials remain on the host."""
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import time

from .agentrq import Client
from .config import DevError, ROOT, private_write, source_info
from .machine import new_id, scrub


def task_control(machine, args):
    if machine.instance.scaffold.name != 'acp':
        raise DevError('Task controls require an ACP instance.')
    machine.require_provisioned()
    client = Client(machine.instance)
    task = client.task(args.task_id)['task']
    if args.action == 'reply':
        if not args.message_file:
            raise DevError('Reply requires --message-file PATH.')
        client.task(args.task_id, '/reply', {'reply': {'text': args.message_file.read_text()}})
    elif args.action == 'cancel':
        try:
            client.task(args.task_id, '/stop', {})
        finally:
            machine.call('systemctl', 'stop', machine.instance.scaffold.service)
        client.task(args.task_id, '/status', {'status': {'value': 'rejected'}}, 'PATCH')
    print(scrub(json.dumps(client.task(args.task_id)['task'] if args.action != 'show' else task, indent=2),
                machine.instance.process_env()))
    return 0


def run_task(machine, args):
    receipt = machine.require_provisioned()
    machine.require_idle()
    client = Client(machine.instance)
    task_id = getattr(args, 'task_id', None)
    active = client.tasks()
    if any(t['id'] != task_id for t in active):
        raise DevError('Workspace has unfinished tasks. Resume with --task-id or cancel them first.')
    if args.command == 'probe':
        prompt = 'Reply exactly ACP-PROBE and mark this task completed. Do not change files.'
    elif getattr(args, 'prompt_file', None):
        prompt = args.prompt_file.read_text()
    elif not task_id:
        raise DevError('ACP run requires --prompt-file PATH or --task-id ID.')
    if task_id:
        client.task(task_id)
        client.task(task_id, '/status', {'status': {'value': 'notstarted'}}, 'PATCH')
    run_id = new_id()
    directory = machine.instance.root / 'reports' / run_id
    started = time.monotonic()
    data = dict(receipt, run_id=run_id, suite=args.command, timeout=args.timeout,
                started_at=datetime.now(timezone.utc).isoformat(), devenv=source_info(ROOT),
                machine=machine.name, events=[], status='running',
                command=['devctl', args.command],
                input={'task_id': task_id} if task_id else {'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()})
    log = []
    code = 2
    service = machine.instance.scaffold.service
    try:
        machine.call('systemctl', 'start', service)
        machine.call('systemctl', 'start', 'crux-codex-live-trace', check=False, capture=True)
        while not client.workspace().get('agentConnected'):
            if time.monotonic() - started >= min(args.timeout, 60):
                raise TimeoutError('ACP gateway did not connect to its workspace.')
            time.sleep(1)
        if not task_id:
            task_id = client.create(prompt, 'Local run ' + run_id)['id']
        data['task_id'] = task_id
        private_write(directory / 'report.json', json.dumps(data, indent=2))
        print(f'AgentRQ task {task_id}; evidence: {directory}/report.json', flush=True)
        previous = None
        while True:
            task = client.task(task_id)['task']
            state = task['status']
            if state != previous:
                data['events'].append({'status': state, 'elapsed_seconds': round(time.monotonic() - started, 2)})
                print('Task status: ' + state, flush=True)
                previous = state
            if state in ('completed', 'rejected', 'blocked'):
                code = 0 if state == 'completed' else 3
                data['task'] = task
                break
            if time.monotonic() - started >= args.timeout:
                raise TimeoutError('Task exceeded the wall time limit.')
            state_result = machine.call('systemctl', 'is-active', service, capture=True, check=False)
            if state_result.stdout.strip() != 'active':
                raise DevError('ACP gateway exited before task completion.')
            time.sleep(1)
    except KeyboardInterrupt:
        code = 130
        log.append('Interrupted by operator.')
    except TimeoutError as error:
        code = 124
        log.append(str(error))
    except Exception as error:
        log.append(f'{type(error).__name__}: {error}')
    finally:
        if code and task_id:
            try:
                client.task(task_id, '/stop', {})
            except Exception as error:
                log.append(f'Stop notification unavailable: {error}')
        machine.call('systemctl', 'stop', service, 'crux-codex-live-trace', check=False, capture=True)
        if code in (124, 130) and task_id:
            try:
                client.task(task_id, '/status', {'status': {'value': 'rejected'}}, 'PATCH')
            except Exception as error:
                log.append(f'Task cancellation state unavailable: {error}')
        try:
            snapshot_code = machine.job('snapshot', [data['started_at']], timeout=30)
            if isinstance(machine.last_report, Path):
                data['snapshot_report'] = str(machine.last_report / 'report.json')
            code = code or snapshot_code
        except Exception as error:
            log.append(f'Evidence snapshot failed: {error}')
            code = code or 2
        data.update(status='succeeded' if code == 0 else 'failed', exit_code=code,
                    elapsed_seconds=round(time.monotonic() - started, 2))
        private_write(directory / 'report.json', scrub(json.dumps(data, indent=2), machine.instance.process_env()) + '\n')
        private_write(directory / 'output.log', scrub('\n'.join(log), machine.instance.process_env()))
        print(scrub('\n'.join(log), machine.instance.process_env()))
        print(f'Evidence: {directory}/report.json; status={data["status"]}')
    return code
