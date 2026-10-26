"""Load deployment contracts from the explicitly selected, trusted CRUX source."""
import hashlib
import importlib.util
import sys
from pathlib import Path


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
