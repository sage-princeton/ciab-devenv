"""Load deployment contracts from the explicitly selected, trusted CRUX source."""
import hashlib
import importlib.util
import json
import sys
from importlib import import_module
from pathlib import Path


def plan(source, specification):
    production = contracts(source, required=True)
    value = json.loads(Path(specification).read_text())
    kind = 'Controller' if value.get('kind') == 'controller' else 'Run'
    model = getattr(production, kind, None)
    if model is None:
        raise ValueError(f'Selected source does not provide {kind} contracts')
    return model.parse(value).plan()


def bundle(source, settings, inputs, output):
    source = Path(source)
    if not (source / 'devops/crux_devops/bundle.py').is_file():
        return None
    production = contracts(source, required=True)
    configuration = {'system_parameter': '/crux/local/system/env'}
    if settings['scaffold'] == 'acp':
        configuration['control_mcp_base'] = 'https://agentrq.test'
    run = production.Run.parse({
        'version': 1, 'name': settings['run_slug'], 'box': 'box',
        'scaffold': {'type': 'agentrq' if settings['scaffold'] == 'acp' else settings['scaffold'],
                     'platform': settings['platform'], 'provider': settings['provider'],
                     'model': settings['model'], 'effort': settings['effort'],
                     'drop_in': 'run-harness', 'configuration': configuration},
        'resources': [{'id': 'box', 'type': 'local.box', 'config': {'region': 'us-east-1'}}],
    })
    return import_module(production.__name__ + '.bundle').assemble(source, run, output, drop_in=inputs)


def contracts(source, *, required=False):
    source = Path(source).resolve()
    package = source / 'devops/crux_devops/__init__.py'
    if not package.is_file():
        if required:
            raise ValueError('Selected source does not provide CRUX deployment contracts')
        return None
    if not package.resolve().is_relative_to(source):
        raise ValueError('Production contracts leave the selected source')
    name = '_ciab_production_' + hashlib.sha256(str(source).encode()).hexdigest()[:16]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, package)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            for key in list(sys.modules):
                if key == name or key.startswith(name + '.'):
                    del sys.modules[key]
            raise
    return sys.modules[name]


def scaffold_settings(source, settings):
    production = contracts(source)
    if production is None:
        return None
    return production.Scaffold.parse({
        'type': 'agentrq' if settings['scaffold'] == 'acp' else settings['scaffold'],
        'platform': settings['platform'], 'provider': settings['provider'],
        'model': settings['model'], 'effort': settings['effort'], 'drop_in': 'run-harness',
    })
