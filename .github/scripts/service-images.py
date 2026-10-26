"""Enumerate fixed image references without reading private instance settings."""
from pathlib import Path

import yaml

images=set()
for path in Path('.').glob('compose*.yaml'):
    for service in yaml.safe_load(path.read_text())['services'].values():
        image=service.get('image','')
        if image and '${' not in image:
            images.add(image)
for image in sorted(images):
    print(image)
