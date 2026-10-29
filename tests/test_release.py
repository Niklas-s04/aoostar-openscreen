import copy
import pytest
from scripts.verify_public_images import validate_config, main


def test_public_release_image_contract():
    config = {'architecture': 'amd64', 'os': 'linux', 'config': {
        'User': '10001:10001', 'Labels': {'org.opencontainers.image.version': '1.0.2'},
        'Healthcheck': {'Test': ['CMD', 'python', '-c', 'healthcheck']}}}
    validate_config(config, '1.0.2')
    for path, value in [('architecture', 'arm64'), ('os', 'windows'), ('User', '0:0')]:
        bad = copy.deepcopy(config)
        (bad if path in ('architecture', 'os') else bad['config'])[path] = value
        with pytest.raises(AssertionError):
            validate_config(bad, '1.0.2')
    with pytest.raises(AssertionError):
        validate_config(config, '1.0.3')


@pytest.mark.parametrize('version', ['latest', '../token', '1.0.2;echo', '1.0.2-rc1'])
def test_public_release_rejects_nonversion_before_network(version):
    with pytest.raises(ValueError):
        main(version)
